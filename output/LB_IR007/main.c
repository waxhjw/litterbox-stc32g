/* IR007：在IR006采样诊断上给三路接收脚使能内部4K上拉。
 * 2026-11-11实测CN3.1 VDD=5.1V供电正常，但P0.6/P1.0/P1.1三路读数仅5~42/4096
 * （约0~35mV），疑似接收芯片开漏输出无外部上拉。本版仅增加上拉使能，
 * 其余行为（三键3秒启停、串口停止、A~F探测、看门狗）逐字节继承IR006。
 * 上拉寄存器：P0PU=0x7EFE10（bit6→P0.6）、P1PU=0x7EFE11（bit0/bit1→P1.0/P1.1），
 * 来源手册stc32g-cn.pdf头文件定义页1767；P_SW2.7已置1访问扩展SFR。
 * 高/低探测与高阻释放仍不等同光学发射确认；遮挡判据仍未接入。
 */
#include "motor_control.h"
#include "motor_ir_guard.h"
#include "array_probe_state.h"
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
#define T0_RELOAD (65536UL-(FOSC+5000UL)/10000UL)
#define UART_RELOAD (65536UL-FOSC/115200UL/4UL)
volatile MotorControl control;
volatile MotorIrGuard guard;
volatile ArrayProbe probe;
volatile unsigned char heartbeat;
unsigned char divider;

void array_release(void)
{
    /* 只释放三个控制脚，不改按键P0.2和其它GPIO；高阻不是光学关闭证明。 */
    P0M1|=0x10; P0M0&=0xEF;
    P5M1|=0x0C; P5M0&=0xF3;
}
unsigned char pressed_keys(void)
{
    unsigned char keys=0;
    if (KEY1==0) keys|=1;
    if (KEY2==0) keys|=2;
    if (KEY3==0) keys|=4;
    return keys;
}
void timer0_isr(void) interrupt 1
{
    heartbeat++;
    if (array_probe_tick(&probe)) array_release();
    if (++divider==100) {
        divider=0;
        motor_control_tick(&control,pressed_keys());
        /* 采样阶段无有效光路判定；保持未接模块也能独立测试电机的约定。 */
        motor_ir_guard_tick(&guard,control.running,IR_UNKNOWN);
        MOTOR_BI=0; MOTOR_FI=guard.actual;
        if (control.running && probe.active) { array_probe_cancel(&probe); array_release(); }
    }
}
void uart_char(unsigned char c)
{
    TI=0; SBUF=c;
    while (TI==0) { } /* 期间中断继续限时释放探测，主循环异常由看门狗恢复。 */
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
    uart_text("IR007 "); uart_text(guard.actual ? "RUN KEYS=" : "STOP KEYS=");
    uart_char(KEY1 ? '1':'0'); uart_char(KEY2 ? '1':'0'); uart_char(KEY3 ? '1':'0');
    uart_text(" PROBE="); hex_digit(probe.active);
    uart_text(" RST="); hex_word(RSTCFG);
    uart_text(" REQ="); hex_digit(control.running);
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
void report_array(void)
{
    unsigned int raw[3];
    unsigned char i, live=probe.active;
    /* 切换通道后丢弃首个转换；全部采完再串口输出，避免UART耗时错过探测窗。 */
    for (i=0;i<3;i++) {
        unsigned char channel=i ? i-1 : 14;
        if (adc_read(channel)==0xFFFF) raw[i]=0xFFFF;
        else raw[i]=adc_read(channel);
    }
    live=(live!=0 && live==probe.active) ? 1:0;
    uart_text("IR007 ADC=");
    for (i=0;i<3;i++) { hex_word(raw[i]); uart_char(i==2 ? '\r':','); }
    uart_text("\nLIVE="); hex_digit(live); uart_text("\r\n");
}
void probe_command(unsigned char command_id)
{
    unsigned char high;
    IE=0;
    if (array_probe_begin(&probe,command_id,control.running)==0) {
        IE=0x82; uart_text("IR007 REJECT\r\n"); return;
    }
    array_release(); high=command_id>3 ? 1:0; if (high) command_id-=3;
    /* 先设单个脚锁存值，再开启该脚推挽；不会读取按键低电平后误锁住P0.2。 */
    if (command_id==1) { ARRAY_TX1=high; P0M1&=0xEF; P0M0|=0x10; }
    else if (command_id==2) { ARRAY_TX2=high; P5M1&=0xFB; P5M0|=0x04; }
    else { ARRAY_TX3=high; P5M1&=0xF7; P5M0|=0x08; }
    IE=0x82;
    report_array();
}
void handle_command(unsigned char value)
{
    if (value=='!' || value=='0') {
        IE=0; motor_control_stop(&control); guard.actual=0; MOTOR_BI=0; MOTOR_FI=0;
        array_probe_cancel(&probe); array_release(); IE=0x82; status();
    } else if (value=='?') status();
    else if (value=='a') report_array();
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
    heartbeat=0; divider=0;
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
