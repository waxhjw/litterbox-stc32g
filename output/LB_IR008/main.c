/* IR008：在IR007采样基础上加入三路38kHz载波发射，并获得"真正的光学闭环"。
 * 2026-11-11实测结论：①两根长条身份已确定——CN3读约2400(3.0V)为黑色圆顶接收条，
 * CN7读约950(1.19V)为透明圆顶发射条；②接收条在CN3、发射条在CN7时读数稳定2400，
 * 说明接收头有电、输出级完好；③但三路发射脚上电即高阻释放，从未输出过38kHz，
 * 故接收头恒为高电平——"有没有对准"在此之前无法判定。
 * 本版新增：Timer0中断周期由100us改为13.16us(145个时钟)，中断内直接翻转
 * P0.4/P5.2/P5.3产生38.13kHz载波（误差0.34%），并保持原有100:1分频节拍
 * （100×13.16us=1.316ms，8200次为10.8ms），使按键长按、遮挡判定等行为不变。
 * 载波采用10ms开1ms窗口，平均占空比5%；支持同步/轮询两种模式。
 * 判定方式：三路ADC从约2400掉到低位即表示该路收到载波（光路通），
 * 不掉则说明该路无光或未对准，可逐路定位。不做遮挡停机与安全承诺。
 */
#include "motor_control.h"
#include "motor_ir_guard.h"
#include "array_probe_state.h"
#include "ir_carrier_state.h"
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
/* 10ms节拍由载波半周期累加得到，8200×13.16us≈10.8ms，原100us×100不变其相对关系。 */
#define TICK_HALF_PER_10MS 8200U
volatile MotorControl control;
volatile MotorIrGuard guard;
volatile ArrayProbe probe;
volatile IrCarrier carrier;
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
    }
    if (array_probe_tick(&probe)) array_release();
    if (++tick_half>=TICK_HALF_PER_10MS) {
        tick_half=0;
        if (++divider>=100) {
            divider=0;
            motor_control_tick(&control,pressed_keys());
            /* 采样阶段无有效光路判定；保持未接模块也能独立测试电机的约定。 */
            motor_ir_guard_tick(&guard,control.running,IR_UNKNOWN);
            MOTOR_BI=0; MOTOR_FI=guard.actual;
            if (control.running && probe.active) { array_probe_cancel(&probe); array_release(); }
        }
    }
}
void uart_char(unsigned char c)
{
    TI=0; SBUF=c;
    while (TI==0) { } /* 期间中断继续限时释放探测/输出载波，主循环异常由看门狗恢复。 */
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
    uart_text("IR008 "); uart_text(guard.actual ? "RUN KEYS=" : "STOP KEYS=");
    uart_char(KEY1 ? '1':'0'); uart_char(KEY2 ? '1':'0'); uart_char(KEY3 ? '1':'0');
    uart_text(" PROBE="); hex_digit(probe.active);
    uart_text(" RST="); hex_word(RSTCFG);
    uart_text(" REQ="); hex_digit(control.running);
    uart_text(" CARRIER="); hex_digit(carrier.mode);
    uart_text(" ARRAY=SAMPLE\r\n"); /* 明示采样阶段，不能当作遮挡保护已经启用。 */
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
/* 采样窗口刻意对齐"静默段"，先关载波再采样，避免载波边沿自己干扰读数。
 * 接收头输出是解调后的电平，静默期内仍然保持低，因此关载波不影响判定。 */
void report_array(void)
{
    unsigned int raw[3];
    unsigned char i;
    for (i=0;i<3;i++) raw[i]=adc_read(i ? i-1 : 14);
    uart_text("IR008 ADC=");
    for (i=0;i<3;i++) { hex_word(raw[i]); uart_char(i==2 ? '\r':','); }
    uart_text("\nCARRIER="); hex_digit(carrier.mode);
    uart_text(" LIVE="); hex_digit(probe.active); uart_text("\r\n");
}
void probe_command(unsigned char command_id)
{
    unsigned char high;
    IE=0;
    if (array_probe_begin(&probe,command_id,control.running)==0) {
        IE=0x82; uart_text("IR008 REJECT\r\n"); return;
    }
    array_release(); high=command_id>3 ? 1:0; if (high) command_id-=3;
    /* 先设单个脚锁存值，再开启该脚推挽；不会读取按键低电平后误锁住P0.2。 */
    if (command_id==1) { ARRAY_TX1=high; P0M1&=0xEF; P0M0|=0x10; }
    else if (command_id==2) { ARRAY_TX2=high; P5M1&=0xFB; P5M0|=0x04; }
    else { ARRAY_TX3=high; P5M1&=0xF7; P5M0|=0x08; }
    IE=0x82;
    report_array();
}
/* 载波开关：'c'=三路同步发，'k'=停。
 * 关载波时先停状态机再把三个脚钉低并释放，保证发射管彻底灭。 */
void carrier_command(unsigned char mode)
{
    IE=0;
    if (mode==CARRIER_IDLE) {
        ir_carrier_stop(&carrier);
        ARRAY_TX1=0; ARRAY_TX2=0; ARRAY_TX3=0;
        array_release();
    } else {
        array_pushpull();
        ir_carrier_start(&carrier);
    }
    IE=0x82;
    status();
}
void handle_command(unsigned char value)
{
    if (value=='!' || value=='0') {
        IE=0; motor_control_stop(&control); guard.actual=0; MOTOR_BI=0; MOTOR_FI=0;
        array_probe_cancel(&probe); IE=0x82;
        carrier_command(CARRIER_IDLE);
    } else if (value=='?') status();
    else if (value=='a') report_array();
    else if (value=='c') carrier_command(CARRIER_SYNC);
    else if (value=='k') carrier_command(CARRIER_IDLE);
    else if (value>='A' && value<='F') probe_command((unsigned char)(value-'A'+1));
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
    motor_control_init(&control); motor_ir_guard_init(&guard); array_probe_init(&probe);
    ir_carrier_init(&carrier); tick_half=0; divider=0;
    heartbeat=0;
    TR0=0; TR1=0; TMOD=0; AUXR=(AUXR|0xC0)&0xFE;
    TH0=(unsigned char)(T0_RELOAD>>8); TL0=(unsigned char)T0_RELOAD;
    TH1=(unsigned char)(UART_RELOAD>>8); TL1=(unsigned char)UART_RELOAD;
    SCON=0x50; TF0=0; TR1=1; TR0=1; IE=0x82; WDT_CONTR=0x33;
    uart_text("BOOT\r\n"); status();
    for (;;) {
        if (last_heartbeat!=heartbeat) { last_heartbeat=heartbeat; WDT_CONTR=0x33; }
        if (previous_run!=guard.actual) { previous_run=guard.actual; status(); }
        if (RI) {
            value=SBUF; RI=0;
            handle_command(value);
        }
    }
}
