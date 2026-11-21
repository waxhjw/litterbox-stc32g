/* IR012：修 IR011 现场实测暴露的"采样跨窗污染下一窗"缺陷。
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
 * 本版仍然只报状态，不做遮挡停机；电机只由按键长按控制。
 * 为了压进C251评估版2KB：删除IR008的直流引脚探测（A~F命令，硬件已确认无需再用）
 * 与瞬时ADC打印，只保留窗口峰值、连续计数和遮挡位图。
 */
#include "motor_control.h"
#include "motor_ir_guard.h"
#include "ir_carrier_state.h"
#include "ir_beam_state.h"
sfr P0=0x80; sfr P0M0=0x94; sfr P0M1=0x93;
sfr P1=0x90; sfr P1M0=0x92; sfr P1M1=0x91;
sfr P2=0xA0; sfr P2M0=0x96; sfr P2M1=0x95;
sfr P3=0xB0; sfr P3M0=0xB2; sfr P3M1=0xB1;
sfr P5=0xC8; sfr P5M0=0xCA; sfr P5M1=0xC9;
sfr P_SW1=0xA2; sfr P_SW2=0xBA;
sfr IE=0xA8; sfr AUXR=0x8E; sfr TMOD=0x89; sfr TCON=0x88;
sfr TL0=0x8A; sfr TH0=0x8C; sfr TL1=0x8B; sfr TH1=0x8D;
sfr SCON=0x98; sfr SBUF=0x99; sfr WDT_CONTR=0xC1; sfr RSTCFG=0xFF;
sfr ADC_CONTR=0xBC; sfr ADC_RES=0xBD; sfr ADC_RESL=0xBE; sfr ADCCFG=0xDE;
sbit MOTOR_BI=P2^0; sbit MOTOR_FI=P2^2;
sbit KEY1=P2^6; sbit KEY2=P0^2; sbit KEY3=P2^7;
sbit ARRAY_TX1=P0^4; sbit ARRAY_TX2=P5^2; sbit ARRAY_TX3=P5^3;
sbit TR0=TCON^4; sbit TF0=TCON^5; sbit TR1=TCON^6;
sbit RI=SCON^0; sbit TI=SCON^1;
#define XREG(addr) (*(unsigned char volatile far *)(addr))
#define ADCTIM XREG(0x7EFEA8UL)
#define FOSC 11059200UL
/* 145个时钟半周期 → 11.0592M/145/2 = 38.13kHz；用-145而非-144避免中断重载偏差。 */
#define T0_HALF_CLOCKS 145UL
#define T0_RELOAD (65536UL-T0_HALF_CLOCKS)
#define UART_RELOAD (65536UL-FOSC/115200UL/4UL)
/* 1ms窗口=76个半周期；9ms静默=684个半周期；合计760个半周期≈10ms。 */
#define BURST_HALF 76U
#define GATE_HALF 684U
/* 恢复IR007的100us基准节拍：8×13.11us≈105us，再100分频≈10.5ms，
 * 与IR007的100us×100=10ms基本一致，长按300拍仍约3秒。
 * 注意IR008误写成8200（8200×13.11us≈108ms），使电机节拍变成10.8秒/拍，
 * 长按需54分钟才触发；本版改回8。 */
#define TICK_HALF_PER_100US 8U
/* 一个窗口内最多采2轮三路ADC。IR011的4轮是错的：ADCTIM=0x3F最长采样时间下
 * 一次转换约100us，12次远超1ms窗口，必然跨窗并把结果记到下一个窗口账上。
 * 2轮约600us，配合BEAM_START_TICKS=55（剩724us）可以整批落在窗内。
 * BEAM_START_TICKS / BEAM_GUARD_TICKS 定义在 ir_beam_state.h，与主循环共用同一份判据。 */
#define BEAM_ROUNDS 2U
volatile MotorControl control;
volatile MotorIrGuard guard;
volatile IrCarrier carrier;
volatile IrBeam beam;
volatile unsigned char heartbeat;
unsigned int tick_half;
unsigned char divider;


void array_release(void)
{
    /* 只释放三个控制脚，不改按键P0.2和其它GPIO；高阻不是光学关闭证明。 */
    P0M1|=0x10; P0M0&=0xEF;
    P5M1|=0x0C; P5M0&=0xF3;
}
void array_pushpull(void)
{
    /* 先写锁存值再切推挽，避免切换瞬间产生毛刺把发射管点亮。 */
    ARRAY_TX1=0; ARRAY_TX2=0; ARRAY_TX3=0;
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
/* 三路同步：同一电平同时落到三个发射脚。 */
void carrier_apply(unsigned char level)
{
    ARRAY_TX1=level; ARRAY_TX2=level; ARRAY_TX3=level;
}
void timer0_isr(void) interrupt 1
{
    unsigned char level;
    heartbeat++;
    if (carrier.mode!=CARRIER_IDLE) {
        level=ir_carrier_tick(&carrier,BURST_HALF,GATE_HALF);
        carrier_apply(level);
        /* burst刚载入=窗口开始；burst归零=窗口结束。两者都只在边界那一拍成立。 */
        if (carrier.burst_ticks==BURST_HALF) ir_beam_open(&beam);
        else if (carrier.burst_ticks==0 && beam.in_window) ir_beam_close(&beam);
    }
    if (++tick_half>=TICK_HALF_PER_100US) {
        tick_half=0;
        if (++divider>=100) {
            divider=0;
            motor_control_tick(&control,pressed_keys());
            /* 采样阶段无有效光路判定；保持未接模块也能独立测试电机的约定。 */
            motor_ir_guard_tick(&guard,control.running,IR_UNKNOWN);
            MOTOR_BI=0; MOTOR_FI=guard.actual;
        }
    }
}
void uart_char(unsigned char c)
{
    TI=0; SBUF=c;
    while (TI==0) { } /* 期间中断继续翻转载波，主循环异常由看门狗恢复。 */
}
void uart_text(const char far *p) { while (*p) uart_char(*p++); }
void hex_digit(unsigned char n) { n&=15; uart_char(n<10 ? n+'0' : n-10+'A'); }
void hex_word(unsigned int n)
{
    hex_digit((unsigned char)(n>>12)); hex_digit((unsigned char)(n>>8));
    hex_digit((unsigned char)(n>>4)); hex_digit((unsigned char)n);
}
void status(void)
{
    uart_text(guard.actual ? "IR9 R K=" : "IR9 S K=");
    uart_char(KEY1 ? '1':'0'); uart_char(KEY2 ? '1':'0'); uart_char(KEY3 ? '1':'0');
    uart_text(" R="); hex_word(RSTCFG);
    uart_text(" Q="); hex_digit(control.running);
    uart_text(" C="); hex_digit(carrier.mode);
    uart_text(" B="); hex_digit(beam.blocked);
    uart_text("\r\n");
}
unsigned int adc_read(unsigned char channel)
{
    unsigned int timeout=2000;
    ADC_CONTR=0xC0|channel; /* 开电源、选通道、清旧FLAG并启动。 */
    while ((ADC_CONTR&0x20)==0) {
        if (--timeout==0) { ADC_CONTR=0; return 0xFFFF; }
    }
    ADC_CONTR&=0xDF;
    return ((unsigned int)ADC_RES<<8)|ADC_RESL;
}
/* 只在窗口内调用：连采几轮取峰值，避开窗口外的暗态读数。
 * 用窗口序号gen守跨窗：一轮3次ADC约300us，窗口只有1ms，
 * 转换之间窗口随时可能翻页。所以先把三个值收到局部变量，
 * 转换完再查gen——变了就整轮丢弃，一个值都不许落地，
 * 因为此时这三个读数分属两个不同窗口，谁都不该认领它。
 * 已经采完的前几轮属于旧窗口（旧窗口close已结算），保留有效。
 * 一轮都没落成则sampled保持0，close直接跳过本窗。 */
void sample_window(void)
{
    unsigned char round, start_gen;
    unsigned int a, b, c;
    beam.fresh=0;
    start_gen=beam.gen;
    for (round=0; round<BEAM_ROUNDS; round++) {
        a=adc_read(14); b=adc_read(0); c=adc_read(1);
        if (beam.gen!=start_gen) break;
        beam.sampled=1;
        ir_beam_add(&beam, a, b, c);
    }
}
/* 最近结算窗口的三路峰值 + 连续未收到光的窗口数 + 遮挡位图，一次读全。
 * 必须读last[]而不是peak[]：打印45字节约3.9ms跨4个窗口，
 * 实时累加器早被open()清零过，读到的只是半截数据，无法诊断。 */
void report_beam(void)
{
    uart_text("IR9 P=");
    hex_word(beam.last[0]); uart_char(',');
    hex_word(beam.last[1]); uart_char(',');
    hex_word(beam.last[2]);
    uart_text(" M=");
    hex_digit(beam.miss[0]); hex_digit(beam.miss[1]); hex_digit(beam.miss[2]);
    uart_text(" B="); hex_digit(beam.blocked); uart_text("\r\n");
}
/* 载波开关：'c'=三路同步发，'k'=停。
 * 开载波时清空判定历史；关载波时停状态机、钉低三个脚并释放，保证发射管彻底灭。 */
void carrier_command(unsigned char mode)
{
    IE=0;
    if (mode==CARRIER_IDLE) {
        ir_carrier_stop(&carrier);
        ARRAY_TX1=0; ARRAY_TX2=0; ARRAY_TX3=0;
        array_release();
    } else {
        array_pushpull();
        ir_beam_init(&beam);
        ir_carrier_start(&carrier);
    }
    IE=0x82;
    status();
}
void handle_command(unsigned char value)
{
    if (value=='!' || value=='0') {
        IE=0; motor_control_stop(&control); guard.actual=0; MOTOR_BI=0; MOTOR_FI=0;
        IE=0x82;
        carrier_command(CARRIER_IDLE);
    } else if (value=='?') status();
    else if (value=='a') report_beam();
    else if (value=='c') carrier_command(CARRIER_SYNC);
    else if (value=='k') carrier_command(CARRIER_IDLE);
}
void main(void)
{
    unsigned char value,last_heartbeat=0,previous_run=0;
    IE=0; MOTOR_BI=0; MOTOR_FI=0;
    P2M1&=0xFA; P2M0|=0x05;
    RSTCFG=(RSTCFG&0xBC)|0x41; P_SW2|=0x80;
    /* 三接收脚内部4K上拉：VDD已实测5.1V仍读0，疑似开漏输出（手册1767页定义）。 */
    XREG(0x7EFE10UL)|=0x40; /* P0PU.bit6 → P0.6/ADC14/REV1 */
    XREG(0x7EFE11UL)|=0x03; /* P1PU.bit1/bit0 → P1.1/REV3、P1.0/ADC0/REV2 */
    array_release();
    P0M0&=0xBB; P0M1=(P0M1&0xFB)|0x40; /* P0.6高阻ADC14，P0.2原按键准双向。 */
    P1M0=(P1M0&0xFC)|0x80; P1M1=(P1M1&0x7F)|0x03; /* ADC0/1输入，旧Q10控制脚保持低。 */
    P1&=0x7F; XREG(0x7EFEB1UL)=0; XREG(0x7EFEC0UL)=0;
    P0|=0x04; P2|=0xC0; P2M0&=0x3F; P2M1&=0x3F;
    P_SW1&=0x3F; P3|=0x03; P3M0=(P3M0&0xFC)|0x02; P3M1=(P3M1&0xFC)|0x01;
    ADCTIM=0x3F; ADCCFG=0x2F; ADC_CONTR=0x80;
    motor_control_init(&control); motor_ir_guard_init(&guard);
    ir_carrier_init(&carrier); ir_beam_init(&beam); tick_half=0; divider=0;
    heartbeat=0;
    TR0=0; TR1=0; TMOD=0; AUXR=(AUXR|0xC0)&0xFE;
    TH0=(unsigned char)(T0_RELOAD>>8); TL0=(unsigned char)T0_RELOAD;
    TH1=(unsigned char)(UART_RELOAD>>8); TL1=(unsigned char)UART_RELOAD;
    SCON=0x50; TF0=0; TR1=1; TR0=1; IE=0x82; WDT_CONTR=0x33;
    uart_text("BOOT\r\n"); status();
    for (;;) {
        if (last_heartbeat!=heartbeat) { last_heartbeat=heartbeat; WDT_CONTR=0x33; }
        if (previous_run!=guard.actual) { previous_run=guard.actual; status(); }
        /* 只在窗口前半段采样：剩余拍数不足BEAM_START_TICKS就整窗放弃。
         * 用burst_ticks而非fresh当门闸——fresh只是个"这一窗开过"的粘滞标志，
         * 主循环被报告打印占住时它早已不反映当前是否真的在发射。 */
        if (carrier.mode!=CARRIER_IDLE && ir_beam_ready(&beam, carrier.burst_ticks))
            sample_window();
        if (RI) {
            value=SBUF; RI=0;
            handle_command(value);
        }
    }
}
