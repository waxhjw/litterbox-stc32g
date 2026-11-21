/*
 * IR005：在冻结IR004上把红外联动默认极性改为高脉冲。
 * 2026-11-10实测本板接收头：TX=4低脉冲判据恒BEAM=2/ARM=0，TX=5高脉冲判据
 * ARM=1且遮挡停机、通光10秒恢复全部通过；故默认link_mode=5，上电即生效。
 * 其余行为（三键长按3秒启停、遮挡暂停、10秒恢复、串口诊断）逐字节继承IR004。
 * 生产CAM：CN4.OUT -> MCU8/P1.4，MCU11/P1.7 -> R42 -> Q10 -> CN8.T-。
 * 接收芯片型号不明，不假设NEC协议，不表示猫检测或安全状态。
 */
#include "motor_control.h"
#include "ir_control.h"
#include "motor_ir_guard.h"
sfr P0=0x80;
sfr P0M0=0x94;
sfr P0M1=0x93;
sfr P1=0x90;
sfr P1M0=0x92;
sfr P1M1=0x91;
sfr P2=0xA0;
sfr P2M0=0x96;
sfr P2M1=0x95;
sfr P3=0xB0;
sfr P3M0=0xB2;
sfr P3M1=0xB1;
sfr P_SW1=0xA2;
sfr P_SW2=0xBA;
sfr IE=0xA8;
sfr AUXR=0x8E;
sfr TMOD=0x89;
sfr TCON=0x88;
sfr TL0=0x8A;
sfr TH0=0x8C;
sfr TL1=0x8B;
sfr TH1=0x8D;
sfr SCON=0x98;
sfr SBUF=0x99;
sfr WDT_CONTR=0xC1;
sfr RSTCFG=0xFF;
sbit MOTOR_BI=P2^0;
sbit MOTOR_FI=P2^2;
sbit KEY_SW1=P2^6;
sbit KEY_SW2=P0^2;
sbit KEY_SW3=P2^7;
sbit IR_RX=P1^4;
sbit IR_TX=P1^7;
sbit TR0=TCON^4;
sbit TF0=TCON^5;
sbit TR1=TCON^6;
sbit RI=SCON^0;
sbit TI=SCON^1;
/* C251使用24位绝对地址访问扩展寄存器；不是0x01xxxx的xdata RAM。 */
#define XREG(addr) (*(unsigned char volatile far *)(addr))
#define PWMA_ENO XREG(0x7EFEB1UL)
#define PWMA_PS XREG(0x7EFEB2UL)
#define PWMA_IOAUX XREG(0x7EFEB3UL)
#define PWMA_CR1 XREG(0x7EFEC0UL)
#define PWMA_EGR XREG(0x7EFEC7UL)
#define PWMA_CCMR4 XREG(0x7EFECBUL)
#define PWMA_CCER1 XREG(0x7EFECCUL)
#define PWMA_CCER2 XREG(0x7EFECDUL)
#define PWMA_PSCRH XREG(0x7EFED0UL)
#define PWMA_PSCRL XREG(0x7EFED1UL)
#define PWMA_ARRH XREG(0x7EFED2UL)
#define PWMA_ARRL XREG(0x7EFED3UL)
#define PWMA_CCR4H XREG(0x7EFEDBUL)
#define PWMA_CCR4L XREG(0x7EFEDCUL)
#define PWMA_BKR XREG(0x7EFEDDUL)
#define PWMA_DTR XREG(0x7EFEDEUL)
#define FOSC 11059200UL
#define T0_RELOAD (65536UL-(FOSC+5000UL)/10000UL)
#define UART_RELOAD (65536UL-FOSC/115200UL/4UL)
volatile MotorControl control;
volatile IrControl ir;
volatile MotorIrGuard guard;
volatile unsigned char heartbeat;
unsigned char divider;

unsigned char read_pressed_keys(void)
{
    unsigned char keys=0;
    /* 机械键另一端接地，仅读0表示相应键按下。 */
    if (KEY_SW1==0) keys|=1;
    if (KEY_SW2==0) keys|=2;
    if (KEY_SW3==0) keys|=4;
    return keys;
}
void motor_stop(void) { MOTOR_FI=0; MOTOR_BI=0; }
void timer0_isr(void) interrupt 1
{
    heartbeat++;
    ir_control_tick(&ir, IR_RX);
    PWMA_ENO=ir.gate ? 0x80 : 0;
    divider++;
    if (divider==100) {
        divider=0;
        motor_control_tick(&control, read_pressed_keys());
        motor_ir_guard_tick(&guard, control.running, ir.beam);
        MOTOR_BI=0;
        MOTOR_FI=guard.actual;
    }
}
void uart_char(unsigned char value)
{
    TI=0; SBUF=value;
    while (TI==0) { } /* 中断继续处理按键与红外；阻塞异常由看门狗恢复。 */
}
/* far覆盖16MB地址；每个只读字符串不足64KB，16位对象内递增足够。 */
void uart_text(const char far *text)
{
    while (*text) uart_char(*text++);
}
void hex_digit(unsigned char value)
{
    value&=15;
    uart_char(value<10 ? value+'0' : value-10+'A');
}
void hex_word(unsigned int value)
{
    hex_digit((unsigned char)(value>>12)); hex_digit((unsigned char)(value>>8));
    hex_digit((unsigned char)(value>>4)); hex_digit((unsigned char)value);
}
void status(void)
{
    uart_text("IR005 ");
    uart_text(guard.actual ? "RUN KEYS=" : "STOP KEYS=");
    uart_char(KEY_SW1 ? '1' : '0'); uart_char(KEY_SW2 ? '1' : '0'); uart_char(KEY_SW3 ? '1' : '0');
    uart_text(" TX="); uart_char((unsigned char)(ir.mode+'0'));
    uart_text(" RAW="); uart_char(IR_RX ? '1' : '0');
    uart_text(" RST="); hex_word(RSTCFG); uart_text("\r\n");
    uart_text("REQ="); uart_char((unsigned char)(control.running+'0'));
    uart_text(" BEAM="); uart_char((unsigned char)(ir.beam+'0'));
    uart_text(" ARM="); uart_char((unsigned char)(guard.armed+'0'));
    uart_text(" WAIT="); hex_word(guard.clear_ticks_left); uart_text("\r\n");
}
void report_ir(void)
{
    unsigned int samples, low, edges;
    /* 同一采样窗口原子复制，避免16位计数读到高低字节混合。 */
    IE=0; samples=ir.samples; low=ir.low; edges=ir.edges;
    ir_control_clear_stats(&ir); IE=0x82;
    uart_text("IR005 S="); hex_word(samples);
    uart_text(" L="); hex_word(low); uart_text(" E="); hex_word(edges);
    uart_text("\r\n");
}
void configure_ir(unsigned char mode)
{
    unsigned int period;
    /* 配置期间强制关闭输出；非法模式也关闭，不能形成常亮命令。 */
    IE=0; ir_control_command(&ir, 0); PWMA_ENO=0; IR_TX=0; IE=0x82;
    PWMA_CR1=0;
    if (mode==0 || mode>5) return;
    if (mode==1) period=307;       /* 36.024kHz */
    else if (mode!=3) period=291;  /* 38.004kHz，包括联动模式 */
    else period=276;              /* 40.070kHz */
    PWMA_CCER1=0; PWMA_CCER2=0;
    PWMA_PS=0; PWMA_IOAUX=0;
    PWMA_PSCRH=0; PWMA_PSCRL=0;
    PWMA_ARRH=(unsigned char)((period-1)>>8);
    PWMA_ARRL=(unsigned char)(period-1);
    PWMA_CCR4H=0; PWMA_CCR4L=(unsigned char)(period/3);
    PWMA_CCMR4=0x60;              /* PWM模式1 */
    PWMA_CCER2=0x40;              /* 仅通道4N，不开4P；单路继承OC4REF，非互补反相。 */
    PWMA_DTR=0; PWMA_BKR=0x80;
    PWMA_EGR=1; PWMA_CR1=1;
    IE=0; ir_control_command(&ir, mode); IE=0x82;
}
void main(void)
{
    unsigned char value, previous_run, previous_mode, last_heartbeat, previous_request, link_mode;
    IE=0;
    motor_stop(); P2M1&=0xFA; P2M0|=0x05;
    /* 厂商RSTCFG示例：运行期使能2.4V低压复位；不改复位脚配置，不写非易失选项。 */
    RSTCFG=(RSTCFG&0xBC)|0x41;
    P_SW2|=0x80;                  /* EAXFR=1 */
    PWMA_ENO=0; PWMA_CR1=0;
    IR_TX=0; P1M0=(P1M0&0xEF)|0x80; P1M1=(P1M1&0x7F)|0x10;
    /* P1.4高阻输入，不主动拉高接收板OUT。P1.7推挽，GPIO锁存保持低。 */
    motor_control_init(&control); ir_control_init(&ir, IR_RX); motor_ir_guard_init(&guard);
    divider=0; heartbeat=0; previous_run=0; previous_mode=0; last_heartbeat=0;
    previous_request=0; link_mode=5; /* 默认高脉冲判据：2026-11-10本板实测TX=5通过，TX=4恒BEAM=2。 */
    P0|=0x04; P0M0&=0xFB; P0M1&=0xFB;
    P2|=0xC0; P2M0&=0x3F; P2M1&=0x3F;
    P_SW1&=0x3F; P3|=0x03;
    P3M0=(P3M0&0xFC)|0x02; P3M1=(P3M1&0xFC)|0x01;
    TR0=0; TR1=0; TMOD=0;
    AUXR=(AUXR|0xC0)&0xFE;
    TH0=(unsigned char)(T0_RELOAD>>8); TL0=(unsigned char)T0_RELOAD;
    TH1=(unsigned char)(UART_RELOAD>>8); TL1=(unsigned char)UART_RELOAD;
    SCON=0x50; TF0=0; TR1=1; TR0=1; IE=0x82; WDT_CONTR=0x33;
    uart_text("BOOT\r\n"); status(); /* 紧接完整IR005身份与TX=0状态。 */
    for (;;) {
        if (last_heartbeat!=heartbeat) { last_heartbeat=heartbeat; WDT_CONTR=0x33; }
        if (previous_request!=control.running) {
            /* 这里的开机指用户测试运行状态；遮挡暂停时请求仍为1，红外保持开启。 */
            previous_request=control.running;
            configure_ir(previous_request ? link_mode : 0);
        }
        if (previous_run!=guard.actual || previous_mode!=ir.mode) {
            previous_run=guard.actual; previous_mode=ir.mode; status();
        }
        if (ir.samples>=5000) report_ir();
        if (RI) {
            value=SBUF; RI=0;
            if (value=='!' || value=='0') {
                IE=0; motor_control_stop(&control); guard.actual=0; motor_stop(); IE=0x82;
                value=0;
            } else if (value=='?') { status(); continue; }
            else if (value=='l' || value=='h') {
                link_mode=value=='l' ? 4 : 5;
                value=control.running ? link_mode : 0;
            } else {
                /* 独立发射测试只在已关机时接受；合并配置与回报出口避免重复代码。 */
                if (control.running) continue;
                value=value=='6' ? 1 : value=='8' ? 2 : value=='4' ? 3 : 255;
                if (value==255) continue;
            }
            configure_ir(value); status();
        }
    }
}
