/* DRUM012 新增待机时的三路定相位采样，正常使用 DRUM011 的窗口判定。
 * 以下是旧版演进记录。当前转换时间和窗口预算见 BEAM_ROUNDS。
 * 版本递增原因：IR011 已烧录并冻结，不能覆盖。
 * IR011 现场现象（COM9，三路全通）：连读六次 P 在 {0F38,03EB,0F20} 与
 *   {03CF,0F5C,03C7} 之间跳，M 在 010/202/303 之间跳，B 恒为 0。
 * 根因有两个：
 *   1) 报告读的是实时累加器 peak[]，open() 每窗清零，45字节@115200≈3.9ms
 *      跨掉4个窗口，读到的只是某一瞬间的半截数据 —— 峰值跳变是假象。
 *   2) 真问题是采样太慢：ADCTIM=0x3F（最长采样时间）+ ADCCFG=0x2F（最慢分频），
 *      一次 adc_read 约100us，4轮×3路共12次≈1200us，必然跨过1ms窗口。
 *      跨窗后的结果被记到下一个窗口的 peak 上，而 sampled=1 又让 close 照常结算
 *      → miss 在 0..3 之间来回跳，永远到不了4，遮挡永远判不出来。
 *      现场读到的 04EE(1262) 这个介于暗/亮之间的值，就是采样保持电容
 *      跨在窗口边界上的直接证据。
 * 修法：
 *   a) 轮数 4→2、起始门槛 45→55 拍（剩724us），让整批尽量落在窗内；
 *   b) 加窗口序号 gen 守跨窗：gen 一变立即停手，这一批不属于任何窗口，
 *      绝不把剩余轮次写进新窗口的累加器；
 *   c) close() 结算时把峰值拷进 last[]，'a' 报 last 而不是实时 peak。
 *
 * 在IR008三路载波基础上加入"发射窗口内取峰值 + 连续N窗确认"的光路判定。
 * 2026-11-11 IR008实测：载波静默时三路 957~984（约1.19V暗态），38.13kHz载波到达
 * 接收头时峰值冲到 3896~3928（约4.8V），三路对称；命中率8%恰好等于1ms/10ms占空比
 * —— 接收输出只在发射窗口内有效，随机时刻读必漏。故本版采样与窗口严格同步：
 * ISR在burst载入那一拍置窗口开、在burst归零那一拍结算，主循环只在窗口内取峰值。
 * 判定：某路连续4个已采样窗口峰值都低于2000才认定遮挡；未采样窗口不参与判定。
 * 有滚筒任务时保持载波以持续监测，结束或取消后停止载波。
 * 为了压进C251评估版2KB：删除IR008的直流引脚探测（A~F命令，硬件已确认无需再用）
 * 与瞬时ADC打印，只保留窗口峰值、连续计数和遮挡位图。
 */
#include "motor_control.h"
#include "drum_board.h"
#include "drum_bench.h"
#include "single_ir.h"
#include "ir_carrier_state.h"
#include "ir_beam_state.h"
#include "tuya_link.h"
sfr P0=0x80; sfr P0M0=0x94; sfr P0M1=0x93;
sfr P1=0x90; sfr P1M0=0x92; sfr P1M1=0x91;
sfr P2=0xA0; sfr P2M0=0x96; sfr P2M1=0x95;
sfr P3=0xB0; sfr P3M0=0xB2; sfr P3M1=0xB1;
sfr P4=0xC0; sfr P4M0=0xB4; sfr P4M1=0xB3;
sfr P5=0xC8; sfr P5M0=0xCA; sfr P5M1=0xC9;
sfr P_SW1=0xA2; sfr P_SW2=0xBA;
sfr IE=0xA8; sfr AUXR=0x8E; sfr TMOD=0x89; sfr TCON=0x88;
sfr IE2=0xAF; sfr IP=0xB8; sfr S3CON=0xAC; sfr S3BUF=0xAD;
sfr T4T3M=0xDD; sfr T3H=0xD4; sfr T3L=0xD5;
sfr TL0=0x8A; sfr TH0=0x8C; sfr TL1=0x8B; sfr TH1=0x8D;
sfr SCON=0x98; sfr SBUF=0x99; sfr WDT_CONTR=0xC1; sfr RSTCFG=0xFF;
sfr ADC_CONTR=0xBC; sfr ADC_RES=0xBD; sfr ADC_RESL=0xBE; sfr ADCCFG=0xDE;
sbit MOTOR_BI=P2^0; sbit MOTOR_FI=P2^2;
sbit KEY1=P2^6; sbit KEY2=P0^2; sbit KEY3=P2^7;
sbit ARRAY_TX1=P0^4; sbit ARRAY_TX2=P5^2; sbit ARRAY_TX3=P5^3;
sbit SINGLE_RX=P1^4;
sbit TR0=TCON^4; sbit TF0=TCON^5; sbit TR1=TCON^6;
sbit RI=SCON^0; sbit TI=SCON^1;
#define XREG(addr) (*(unsigned char volatile far *)(addr))
#define ADCTIM XREG(0x7EFEA8UL)
#define SINGLE_PWM_ENABLE XREG(0x7EFEB1UL)
#define SINGLE_PWM_CONTROL XREG(0x7EFEC0UL)
#define FOSC 11059200UL
/* 145个时钟半周期 → 11.0592M/145/2 = 38.13kHz；用-145而非-144避免中断重载偏差。 */
#define T0_HALF_CLOCKS 145UL
#define T0_RELOAD (65536UL-T0_HALF_CLOCKS)
#define UART_RELOAD (65536UL-FOSC/115200UL/4UL)
/* 1ms窗口=76个半周期；9ms静默=684个半周期；合计760个半周期≈10ms。 */
#define BURST_HALF 76U
#define GATE_HALF 684U
/* 长按和恢复计时每 760 个半周期推进一次，约 9.964 ms。 */
#define MOTOR_CONTROL_TICKS (BURST_HALF+GATE_HALF)
/* 三路窗口结束后，单路在静默区独立发射约 1ms，再保留接收窗口。 */
#define SINGLE_OPEN_GATE 610U
#define SINGLE_OFF_GATE 534U
#define SINGLE_CLOSE_GATE 34U
#define INSPECT_OFF 0U
#define INSPECT_BOTH 1U
#define INSPECT_ARRAY 2U
#define INSPECT_20MS 3U
#define INSPECT_40MS 4U
#define INSPECT_PHASE_SCAN 5U
#define PHASE_SAMPLES 16U
#define PHASE_CELLS 9U
#define PHASE_LIMIT_TICKS 225U
#define PHASE_RUNNING 1U
#define PHASE_DONE 2U
#define PHASE_TIMEOUT 3U
#define PHASE_CANCELED 4U
/* 一个窗口至多采两轮。每轮三次 12 位转换约 408us，另留软件收尾时间。
 * 第一轮与后续每轮的入口时限见 ir_beam_state.h。 */
#define BEAM_ROUNDS 2U
#define ADC_INVALID 0xFFFFU
volatile MotorControl control;
volatile DrumCycle drum;
static volatile DrumBench bench;
static DrumAuto automatic;
volatile IrCarrier carrier;
volatile IrBeam beam;
static volatile SingleIr single_ir;
static volatile SingleIr single_frame;
static volatile unsigned short single_windows, single_clear_windows;
static volatile unsigned short single_clear_run, single_longest_clear;
static volatile unsigned char single_skip;
volatile unsigned char heartbeat;
unsigned int motor_tick;
volatile bit carrier_requested;
static volatile unsigned char inspect_light;
typedef struct {
    unsigned int low, high;
    unsigned char count, light;
} PhaseCell;
static PhaseCell phase_cells[PHASE_CELLS];
static const unsigned char phase_inputs[PHASE_CELLS]={14,0,1,14,0,1,14,0,1};
static unsigned char phase_state, phase_cell, phase_target, phase_gen, phase_started;
static volatile unsigned char radar_idle=DRUM_BOARD_RADAR_IDLE;
static volatile unsigned char app_owner, control_clock, control_report, drum_job, bin_ready;

#include "wifi_uart.h"

static void single_pwm_init(void)
{
    /* 沿用 IR005 的 P1.7/PWM4N 经 Q10，38kHz、约 1/3 占空比。 */
    SINGLE_PWM_ENABLE=0;
    SINGLE_PWM_CONTROL=0;
    XREG(0x7EFEB2UL)=0; XREG(0x7EFEB3UL)=0;
    XREG(0x7EFECCUL)=0; XREG(0x7EFECDUL)=0;
    XREG(0x7EFED0UL)=0; XREG(0x7EFED1UL)=0;
    XREG(0x7EFED2UL)=1; XREG(0x7EFED3UL)=34; /* 290+1 个时钟。 */
    XREG(0x7EFEDBUL)=0; XREG(0x7EFEDCUL)=97;
    XREG(0x7EFECBUL)=0x60; XREG(0x7EFECDUL)=0x40;
    XREG(0x7EFEDEUL)=0; XREG(0x7EFEDDUL)=0x80;
    XREG(0x7EFEC7UL)=1; SINGLE_PWM_CONTROL=1;
}

void array_release(void)
{
    /* 只释放三个控制脚，不改按键P0.2和其它GPIO；高阻不是光学关闭证明。 */
    P0M1|=0x10; P0M0&=0xEF;
    P5M1|=0x0C; P5M0&=0xF3;
}
/* 直接写三路引脚。旧工具链会把载波函数的参数误写到 SFR 0x8C（TH0）。 */
#define CARRIER_APPLY(level) do { ARRAY_TX1=(level); ARRAY_TX2=(level); ARRAY_TX3=(level); } while (0)
void array_pushpull(void)
{
    /* 先写锁存值再切推挽，避免切换瞬间产生毛刺把发射管点亮。 */
    CARRIER_APPLY(0);
    P0M1&=0xEF; P0M0|=0x10;
    P5M1&=0xF3; P5M0|=0x0C;
}
unsigned char pressed_keys(void)
{
    unsigned char keys=0;
    if (KEY1==0) keys|=1;
    if (KEY2==0) keys|=2;
    if (KEY3==0) keys|=4;
    return keys;
}
/* 主循环与串口共用配置入口，只在切换模式时短暂关闭中断。 */
void update_carrier(void)
{
    unsigned char enabled=carrier_requested;
    if (enabled==carrier.mode) return;
    IE=0;
    SINGLE_PWM_ENABLE=0;
    single_ir.state=SINGLE_UNKNOWN;
    single_skip=0;
    if (enabled) {
        single_windows=0;
        single_clear_windows=0;
        single_clear_run=0;
        single_longest_clear=0;
        array_pushpull();
        ir_beam_init(&beam);
        ir_carrier_start(&carrier);
    } else {
        ir_carrier_stop(&carrier);
        CARRIER_APPLY(0);
        array_release();
    }
    IE=0x82;
}

static void control_drum(void)
{
    unsigned char key, input, position, app_request, auto_request=0, auto_ready, output, request_job=0, trial_output;
    control_clock++;
    position=drum_board_position();
    input=drum_board_aux_inputs((P1>>5)&3);
    bin_ready=(input & DRUM_BIN_READY)!=0;
    if (((P4&0x80)|1)==radar_idle) input|=DRUM_RADAR_CLEAR;
    if (carrier.mode && beam.age<BEAM_CONFIRM && beam.seen==7 && beam.blocked==0)
        input|=DRUM_LIGHT_CLEAR;
    if (carrier.mode && inspect_light<INSPECT_20MS && single_ir.state==SINGLE_CLEAR)
        input|=DRUM_SINGLE_CLEAR;

    key=motor_control_tick(&control,pressed_keys());
    app_request=app_start_pending;
    app_start_pending=0;
    if (key & KEY_LONG) {
        if (drum.phase!=DRUM_IDLE) {
            drum_stop(&drum, DRUM_CANCELED);
            app_request=0;
        } else if (key==(KEY_LONG|KEY_CLEAN) && position==drum_board.home &&
            drum.stable==position && drum.sample_count==DRUM_STABLE_SAMPLES &&
            drum_config_ready(&drum_board) &&
            (input & (DRUM_RADAR_CLEAR|DRUM_PRESENCE_VALID|DRUM_OCCUPIED|DRUM_DRIVE_OK|DRUM_BIN_READY))==
            (DRUM_RADAR_CLEAR|DRUM_PRESENCE_VALID|DRUM_DRIVE_OK|DRUM_BIN_READY)) {
            /* 本机长按在已回原点时确认故障。手势本身不启动滚筒。 */
            drum.fault=DRUM_OK;
            dp_paused=0;
            app_request=0;
        } else if (key==(KEY_LONG|DRUM_EMPTY_KEY)) {
            request_job=DRUM_JOB_EMPTY;
            app_request=0;
        }
        drum_auto_reset(&automatic);
    } else if (key==KEY_CLEAN && drum.phase!=DRUM_IDLE) {
        dp_paused^=1;
    } else if (key && key==DRUM_SMOOTH_KEY) {
        request_job=DRUM_JOB_SMOOTH;
    }
    if (dp_paused) input|=DRUM_PAUSED;

    auto_ready=drum_config_ready(&drum_board) && (input & DRUM_PRESENCE_VALID);
    if (dp_auto_level && auto_ready && (input & DRUM_PAUSED)==0 &&
        drum.phase==DRUM_IDLE && drum.fault==DRUM_OK && key==0) {
        /* 约 10 分钟，保持在 16 位节拍范围内。可选延时等产品数据点确认后接入。 */
        auto_request=drum_auto_tick(&automatic,input,DRUM_AUTO_DELAY_TICKS);
    } else {
        drum_auto_reset(&automatic);
    }

    /* 手动与自动共用位置和保护闸门。已经有任务时，不排队也不改归属。 */
    if (drum.phase==DRUM_IDLE) {
        if (request_job==0 && (app_request || key==KEY_CLEAN || auto_request))
            request_job=DRUM_JOB_CLEAN;
        if (request_job && inspect_light<INSPECT_20MS &&
            drum_request(&drum,drum_job_config(request_job),input)) {
            drum_job=request_job;
            app_owner=app_request && request_job==DRUM_JOB_CLEAN;
            inspect_light=INSPECT_OFF;
            drum_auto_reset(&automatic);
        }
    }
    drum_tick(&drum,drum_job_config(drum_job),position,input);
    if (bench.phase!=BENCH_IDLE && pressed_keys())
        bench_stop(&bench,BENCH_STOPPED);
    trial_output=bench_tick(&bench,input,link_network==4,app_request && bench_release_seen);
    carrier_requested=(drum.phase!=DRUM_IDLE) || (bench.phase>=BENCH_WAIT_LIGHT) || inspect_light;
    if (drum.phase==DRUM_IDLE) { app_owner=0; drum_job=0; }

    /* 目标限位首个采样就撤销电机输出，两个方向不会同时拉高。 */
    output=DRUM_MECHANICS_VERIFIED ? drum.output : trial_output;
    if (output==DRUM_REVERSE) {
        MOTOR_FI=0;
        MOTOR_BI=1;
    } else {
        MOTOR_BI=0;
        MOTOR_FI=(output==DRUM_FORWARD);
    }
    control_report=output ? DP_CLEANING :
        ((drum.phase!=DRUM_IDLE || bench.phase>=BENCH_WAIT_LIGHT) ? DP_WAITING : DP_STANDBY);
    if (output && (app_owner || trial_output)) control_report|=DP_APP_OUTPUT;
    if (dp_paused) control_report|=DP_PAUSE_APPLIED;
    if (dp_auto_level && auto_ready) control_report|=DP_AUTO_ACTIVE;
}

static void single_ir_quiet_tick(unsigned short gate)
{
    if (gate==SINGLE_OPEN_GATE) {
        if (single_skip) return;
        single_ir_open(&single_ir,SINGLE_RX);
        SINGLE_PWM_ENABLE=0x80;
    } else if (gate==SINGLE_OFF_GATE) {
        SINGLE_PWM_ENABLE=0;
    } else if (gate==SINGLE_CLOSE_GATE) {
        if (single_skip) {
            single_skip--;
            return;
        }
        single_ir_close(&single_ir);
        if (inspect_light==INSPECT_BOTH || inspect_light>=INSPECT_20MS) {
            /* 只在诊断模式记录已完成的窗口。在载波静默段锁存，避免读取半途重置的计数。 */
            single_windows++;
            if (single_ir.state==SINGLE_CLEAR) {
                single_clear_windows++;
                single_clear_run++;
                if (single_clear_run>single_longest_clear) single_longest_clear=single_clear_run;
            } else single_clear_run=0;
            single_frame.quiet=single_ir.quiet;
            single_frame.samples=single_ir.samples;
            single_frame.high=single_ir.high;
            single_frame.edges=single_ir.edges;
            single_frame.first=single_ir.first;
            single_frame.last=single_ir.last;
            /* 跳过完整的单路窗口以改变间隔，三路载波和当前束的脉宽照旧。 */
            if (inspect_light==INSPECT_20MS) single_skip=1;
            else if (inspect_light==INSPECT_40MS) single_skip=3;
        }
    } else if (gate>SINGLE_CLOSE_GATE && gate<SINGLE_OPEN_GATE && (gate&7)==2 && single_skip==0) {
        single_ir_sample(&single_ir,SINGLE_RX);
    }
}

void timer0_isr(void) interrupt 1
{
    heartbeat++;
    if (carrier.mode!=CARRIER_IDLE) {
        /* 三路载波期间只推进三路时序，单路使用三路关断后的独立窗口。 */
        if (carrier.burst_ticks) {
            if (--carrier.burst_ticks) {
                carrier.phase^=1;
                if (carrier.phase) CARRIER_APPLY(1);
                else CARRIER_APPLY(0);
            } else {
                CARRIER_APPLY(0);
                carrier.gate_ticks=GATE_HALF;
                ir_beam_close(&beam);
            }
        } else if (--carrier.gate_ticks==0) {
            /* 76 个半周期从高电平开始，最后一个半周期为低电平。 */
            carrier.burst_ticks=BURST_HALF;
            carrier.phase=1;
            CARRIER_APPLY(1);
            ir_beam_open(&beam);
        } else if (inspect_light!=INSPECT_ARRAY && inspect_light!=INSPECT_PHASE_SCAN) {
            single_ir_quiet_tick(carrier.gate_ticks);
        }
    }
    if (++motor_tick==MOTOR_CONTROL_TICKS) {
        motor_tick=0;
        control_drum();
    }
}
void uart_char(unsigned char c)
{
    TI=0; SBUF=c;
    while (TI==0) { } /* 期间中断继续翻转载波，主循环异常由看门狗恢复。 */
}
void uart_text(const char far *p) { while (*p) uart_char(*p++); }
void uart_eol(void) { uart_char('\r'); uart_char('\n'); }
void hex_digit(unsigned char n) { n&=15; uart_char(n<10 ? n+'0' : n-10+'A'); }
void hex_word(unsigned int n)
{
    hex_digit((unsigned char)(n>>12)); hex_digit((unsigned char)(n>>8));
    hex_digit((unsigned char)(n>>4)); hex_digit((unsigned char)n);
}
static void app_status(void)
{
    unsigned short completed;
    IE=0; completed=drum.completed; IE=0x82;
    uart_text("DRUM012 N="); hex_digit(link_network>>4); hex_digit(link_network);
    uart_text(" H="); hex_word(link_heartbeat);
    uart_text(" D="); hex_word(link_dp);
    uart_text(" R="); hex_word(dp_reports);
    uart_text(" E="); hex_word(link_errors);
    uart_text(" T="); hex_word(wifi_fail);
    uart_text(" X="); hex_word(dp_invalid);
    uart_text(" Q="); hex_digit(drum.phase!=DRUM_IDLE || bench.phase>=BENCH_WAIT_LIGHT);
    uart_text(" V="); hex_digit(dp_paused);
    uart_text(" I="); hex_word(dp_last_id);
    uart_text(" U="); hex_digit(dp_last_value);
    uart_text(" W="); hex_digit(app_owner);
    uart_text(" O="); hex_digit(P2&5);
    uart_text(" Y="); hex_word(control_clock);
    uart_text(" S="); hex_digit(control_report & DP_STATUS_MASK);
    uart_text(" L="); hex_digit(dp_manual_level);
    uart_text(" J="); hex_digit(drum.phase);
    uart_text(" F="); hex_digit(drum.fault);
    uart_text(" A="); hex_digit((control_report & DP_AUTO_ACTIVE)!=0);
    uart_text(" G="); hex_digit(drum_job);
    uart_text(" Z="); hex_word(completed);
    uart_text(" B="); hex_digit(bin_ready);
    uart_text(" P="); hex_digit(drum.stable);
    uart_text(" M="); hex_digit(bench.phase);
    uart_text(" C="); hex_digit(bench.result);
    uart_text(" K="); hex_digit(bench.turns);
    uart_eol();
}
/* 短串口字段使用统一格式，保留原有文本协议。 */
void hex_field(unsigned char label, unsigned char value)
{
    uart_char(' '); uart_char(label); uart_char('=');
    hex_digit(value);
}
void status(void)
{
    unsigned char reset_config=RSTCFG;
    uart_text("IRC "); uart_char((P2&5) ? 'R':'S'); uart_text(" K=");
    uart_char(KEY1 ? '1':'0'); uart_char(KEY2 ? '1':'0'); uart_char(KEY3 ? '1':'0');
    uart_text(" R="); hex_word(reset_config);
    hex_field('Q', drum.phase!=DRUM_IDLE || bench.phase>=BENCH_WAIT_LIGHT);
    hex_field('C', carrier.mode);
    hex_field('B', beam.blocked);
    hex_field('D', P4>>7); /* P4.7 原始电平，0/1 只表示低/高。 */
    uart_eol();
}
unsigned int adc_read(unsigned char channel)
{
    unsigned int timeout=2000;
    /* 上次转换若超时且仍在进行，不能重启或把残留结果当成本通道。 */
    if (ADC_CONTR&0x40) return ADC_INVALID;
    ADC_CONTR=0xC0|channel; /* 保持 ADC 供电，选通道并清旧 FLAG 后启动。 */
    _nop_(); _nop_();       /* STC32G 手册查询例程在读 FLAG 前留出间隔。 */
    while ((ADC_CONTR&0x20)==0) {
        if (--timeout==0) return ADC_INVALID;
    }
    ADC_CONTR&=0xDF;
    return ((unsigned int)ADC_RES<<8)|ADC_RESL;
}
/* 三路都转换完成后，根据窗口序号确认仍在同一窗口才提交。
 * 余量不足就结束本次采样，先前已经提交的有效轮次照常结算。 */
void sample_window(void)
{
    unsigned char round, committed, start_gen;
    unsigned int a, b, c;
    start_gen=beam.gen;
    for (round=0; round<BEAM_ROUNDS; round++) {
        if (carrier.burst_ticks<BEAM_GUARD_TICKS || beam.gen!=start_gen) break;
        a=adc_read(14);
        if (a==ADC_INVALID) break;
        b=adc_read(0);
        if (b==ADC_INVALID) break;
        c=adc_read(1);
        if (c==ADC_INVALID) break;
        IE=0;
        committed=beam.in_window && beam.gen==start_gen;
        if (committed) {
            beam.sampled=1;
            ir_beam_add(&beam, a, b, c);
        }
        IE=0x82;
        if (committed==0) break;
    }
}

static void phase_scan_begin(void)
{
    unsigned char i;
    for (i=0; i<PHASE_CELLS; i++) {
        phase_cells[i].count=0;
        phase_cells[i].light=0;
        phase_cells[i].low=ADC_INVALID;
        phase_cells[i].high=0;
    }
    phase_state=PHASE_RUNNING;
    phase_cell=0;
    phase_target=60;
    phase_gen=0; /* 开发射会清零窗口序号，第一束的序号为 1。 */
    phase_started=control_clock;
}

static void phase_scan_finish(unsigned char state)
{
    IE=0;
    phase_state=state;
    inspect_light=INSPECT_OFF;
    carrier_requested=0;
    app_start_pending=0;
    IE=0x82;
    update_carrier();
}

/* 同一束只采一路。轮流用三个新窗口得到同相位的 REV1/2/3 读数，
 * 整组重复后比较发射开始后约 210、446、682us 的采样结果。 */
static void phase_scan_tick(void)
{
    unsigned char gen=beam.gen, count, hits;
    unsigned int value;
    if ((unsigned char)(control_clock-phase_started)>=PHASE_LIMIT_TICKS) {
        phase_scan_finish(PHASE_TIMEOUT);
        return;
    }
    if (gen==phase_gen || carrier.burst_ticks!=phase_target) return;
    phase_gen=gen;
    value=adc_read(phase_inputs[phase_cell]);
    if (value==ADC_INVALID || beam.gen!=gen || !beam.in_window) return;

    count=phase_cells[phase_cell].count+1U;
    hits=phase_cells[phase_cell].light;
    if (value>=BEAM_THRESHOLD && value<BEAM_RAIL) hits++;
    phase_cells[phase_cell].count=count;
    phase_cells[phase_cell].light=hits;
    if (value<phase_cells[phase_cell].low) phase_cells[phase_cell].low=value;
    if (value>phase_cells[phase_cell].high) phase_cells[phase_cell].high=value;
    if (++phase_cell==PHASE_CELLS) {
        if (count==PHASE_SAMPLES) {
            phase_scan_finish(PHASE_DONE);
            return;
        }
        phase_cell=0;
    }
    phase_target=phase_cell<3 ? 60 : (phase_cell<6 ? 42 : 24);
}

static void phase_scan_report(void)
{
    unsigned char i;
    uart_text("IRP"); hex_field('S',phase_state);
    for (i=0; i<PHASE_CELLS; i++) {
        uart_char(' ');
        hex_digit(phase_cells[i].count>>4); hex_digit(phase_cells[i].count);
        hex_digit(phase_cells[i].light>>4); hex_digit(phase_cells[i].light);
        hex_word(phase_cells[i].low); hex_word(phase_cells[i].high);
    }
    uart_eol();
}
/* 最近结算窗口的三路峰值 + 连续未收到光的窗口数 + 遮挡位图，一次读全。
 * 必须读last[]而不是peak[]：打印45字节约3.9ms跨4个窗口，
 * 实时累加器早被open()清零过，读到的只是半截数据，无法诊断。 */
void report_beam(void)
{
    unsigned int peaks[3];
    unsigned char misses[3], blocked, i;
    IE=0;
    for(i=0; i<3; i++) {
        peaks[i]=beam.last[i];
        misses[i]=beam.miss[i];
    }
    blocked=beam.blocked;
    IE=0x82;
    uart_text("IRC P=");
    for(i=0; i<3; i++) {
        if(i) uart_char(',');
        hex_word(peaks[i]);
    }
    uart_text(" M=");
    for(i=0; i<3; i++) hex_digit(misses[i]);
    hex_field('B', blocked); uart_eol();
}
static void report_single(void)
{
    unsigned short windows, clear, longest;
    unsigned char quiet, samples, high, edges, first, last;
    IE=0;
    windows=single_windows;
    clear=single_clear_windows;
    longest=single_longest_clear;
    quiet=single_frame.quiet;
    samples=single_frame.samples;
    high=single_frame.high;
    edges=single_frame.edges;
    first=single_frame.first;
    last=single_frame.last;
    IE=0x82;
    uart_text("IRS W="); hex_word(windows);
    uart_text(" V="); hex_word(clear);
    if (windows) {
        hex_field('Q',quiet);
        uart_text(" N="); hex_word(samples);
        uart_text(" H="); hex_word(high);
        uart_text(" E="); hex_word(edges);
        uart_text(" F="); hex_word(first);
        hex_field('L',last);
        uart_text(" C="); hex_word(longest);
    }
    uart_eol();
}
void handle_command(unsigned char value)
{
    unsigned short recovery;
    unsigned char optical, beam_state;
    if (value=='a') { report_beam(); return; }
    if (value=='z') { report_single(); return; }
    if (value=='y') { phase_scan_report(); return; }
    if (value=='e') {
        /* 采样在待机台架模式开始，完成后才恢复接收启动请求。 */
        IE=0;
        if (drum.phase==DRUM_IDLE && bench.phase==BENCH_IDLE &&
            carrier.mode==CARRIER_IDLE && (P2&5)==0) {
            phase_scan_begin();
            app_start_pending=0;
            inspect_light=INSPECT_PHASE_SCAN;
            carrier_requested=1;
        }
        IE=0x82;
        update_carrier();
        status();
        return;
    }
    if (value=='d') {
        IE=0;
        recovery=bench.recovery_ticks;
        optical=single_ir.state;
        beam_state=carrier.mode && beam.age<BEAM_CONFIRM && beam.seen==7 ? beam.blocked : 8;
        IE=0x82;
        uart_text("IRX R="); hex_digit(((P4&0x80)|1)!=radar_idle);
        uart_text(" A="); hex_digit(beam_state);
        uart_text(" S="); hex_digit(optical);
        uart_text(" T="); hex_word(recovery);
        uart_eol(); return;
    }
    if (value=='w') { app_status(); return; }
    if (value=='p') { if (drum.phase==DRUM_IDLE && bench.phase==BENCH_IDLE) wifi_pair(); app_status(); return; }
    if (value=='b' && !link_heartbeat && !tx_busy) {
        IE=0;
        wifi_fast^=1;
        wifi_uart_baud(wifi_fast ? WIFI_RELOAD(115200UL) : WIFI_RELOAD(9600UL));
        IE=0x82;
        app_status();
        return;
    }
    if (value=='h') {
        /* 一次读同一个端口。位 1 为 HLR1(P1.6)，位 0 为 HLR2(P1.5)，两路都来自集便仓。 */
        uart_char('H'); hex_digit((P1>>5)&3); uart_eol();
        return;
    }
    IE=0;
    if (value=='!' || value=='0') {
        motor_control_stop(&control);
        drum_stop(&drum,drum.phase==DRUM_IDLE ? drum.fault : DRUM_CANCELED);
        if (bench.phase!=BENCH_IDLE) bench_stop(&bench,BENCH_STOPPED);
        drum_auto_reset(&automatic);
        inspect_light=INSPECT_OFF; carrier_requested=0; MOTOR_BI=0; MOTOR_FI=0;
        if (phase_state==PHASE_RUNNING) phase_state=PHASE_CANCELED;
        app_owner=0; app_start_pending=0;
        drum_job=0;
        control_report=dp_paused ? DP_PAUSE_APPLIED : 0;
    } else if (value=='g') {
        /* 只在本机串口明确授权后允许下一次手机请求。之前的请求与释放值作废。 */
        if (drum.phase==DRUM_IDLE && bench.phase==BENCH_IDLE && inspect_light<INSPECT_20MS && link_network==4 &&
            dp_paused==0 && (P2&5)==0 && ((P1>>5)&3)!=3 &&
            ((P4&0x80)|1)==radar_idle && pressed_keys()==0) {
            app_start_pending=0;
            bench_release_seen=0;
            inspect_light=INSPECT_OFF;
            carrier_requested=0;
            bench_arm(&bench);
        }
    } else if (value=='H' || value=='L') {
        /* 台架在停止时选择实测触发电平。掉电清除，未知极性时一直禁止启动。 */
        if (drum.phase==DRUM_IDLE && bench.phase==BENCH_IDLE && drum_config_ready(&drum_board)==0)
            radar_idle=value=='H' ? 1 : 0x81;
    } else if (value=='c' || value=='j' || value=='k' || value=='u' || value=='v') {
        if (drum.phase==DRUM_IDLE && bench.phase==BENCH_IDLE) {
            /* u/v 只用于 20/40ms 台架对照，先用 k 结束诊断才能准备试转。 */
            if (value=='k') {
                inspect_light=INSPECT_OFF;
                if (phase_state==PHASE_RUNNING) phase_state=PHASE_CANCELED;
            }
            else if (carrier.mode==CARRIER_IDLE) {
                switch (value) {
                case 'j': inspect_light=INSPECT_ARRAY; break;
                case 'u': inspect_light=INSPECT_20MS; break;
                case 'v': inspect_light=INSPECT_40MS; break;
                default: inspect_light=INSPECT_BOTH; break;
                }
            }
            carrier_requested=inspect_light!=INSPECT_OFF;
        }
    } else if (value!='?') {
        /* 旧版对下载同步字节 0x7F 也回报状态，导致 ISP 接收混入应用数据。 */
        IE=0x82;
        return;
    }
    IE=0x82;
    update_carrier();
    status();
}
void main(void)
{
    unsigned char value,last_heartbeat=0,previous_run=0;
    IE=0; MOTOR_BI=0; MOTOR_FI=0;
    P2M1&=0xFA; P2M0|=0x05;
    RSTCFG=(RSTCFG&0xBC)|0x41; P_SW2|=0x80;
    /* 三接收脚内部4K上拉：VDD已实测5.1V仍读0，疑似开漏输出（手册1767页定义）。 */
    XREG(0x7EFE10UL)|=0x40; /* P0PU.bit6 → P0.6/ADC14/REV1 */
    /* P1.5/6 霍尔输入启用上拉，避免断线后浮空误判低。保留红外上拉。 */
    XREG(0x7EFE11UL)|=0x63;
    array_release();
    P0M0&=0xBB; P0M1=(P0M1&0xFB)|0x40; /* P0.6高阻ADC14，P0.2原按键准双向。 */
    /* P1.5/6 设为输入，许可只读取引脚电平。 */
    P1M0=(P1M0&0x8C)|0x80; P1M1=(P1M1&0x7F)|0x73;
    P1&=0x7F; single_pwm_init();
    P4M0&=0x7F; P4M1|=0x80; /* P4.7 高阻，主板 R18 提供外部上拉。 */
    P0|=0x04; P2|=0xC0; P2M0&=0x3F; P2M1&=0x3F;
    P_SW1&=0x3F; P3|=0x03; P3M0=(P3M0&0xBC)|0x02; P3M1=(P3M1&0xFC)|0x41;
    P_SW2|=2;
    P5|=3; P5M0=(P5M0&0xFC)|2; P5M1=(P5M1&0xFC)|1;
    wifi_uart_baud(WIFI_RELOAD(9600UL));
    IP|=2;  /* Timer0 可抢占 UART3，载波窗口保持原节拍。 */
    IE2|=8;
    ADCTIM=0x3F; ADCCFG=0x2F; ADC_CONTR=0x80;
    /* C 启动代码清零状态。初始按键按下模型要求先松手才能触发。 */
    control.candidate=1;
    drum.stable=DRUM_POSITION_UNKNOWN;
    drum.fault=drum_config_ready(&drum_board) ? DRUM_OK : DRUM_UNCOMMISSIONED;
    /* 首次打开载波时由 update_carrier 初始化光路窗口。 */
    TR0=0; TR1=0; TMOD=0; AUXR=(AUXR|0xC0)&0xFE;
    TH0=(unsigned char)(T0_RELOAD>>8); TL0=(unsigned char)T0_RELOAD;
    TH1=(unsigned char)(UART_RELOAD>>8); TL1=(unsigned char)UART_RELOAD;
    SCON=0x50; TF0=0; TR1=1; TR0=1; IE=0x82; WDT_CONTR=0x33;
    uart_text("BOOT\r\n"); status();
    for (;;) {
        if (last_heartbeat!=heartbeat) { last_heartbeat=heartbeat; WDT_CONTR=0x33; }
        update_carrier();
        if (previous_run!=(P2&5)) { previous_run=P2&5; status(); }
        /* 只在窗口前半段采样：剩余拍数不足BEAM_START_TICKS就整窗放弃。
         * 用burst_ticks而非fresh当门闸——fresh只是个"这一窗开过"的粘滞标志，
         * 主循环被报告打印占住时它早已不反映当前是否真的在发射。 */
        if (inspect_light==INSPECT_PHASE_SCAN)
            phase_scan_tick();
        else if (carrier.mode!=CARRIER_IDLE && ir_beam_ready(&beam, carrier.burst_ticks))
            sample_window();
        if (RI) {
            value=SBUF; RI=0;
            handle_command(value);
        }
        wifi_service();
    }
}
