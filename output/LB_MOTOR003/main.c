/*
 * LB_MOTOR003：生产板STC32G8K64 + SS6625E + 三个板载机械键诊断。
 * 用户明确授权：持续单方向转动，任意机械键长按3s启停，覆盖原程序。
 * 生产CAM/贴片图核对：BI=P2.0经R10；FI=P2.2经R8。
 * SW1=P2.6，SW2=P0.2，SW3=P2.7；按键另一端为MCU第17脚地网。
 * 烧录时电机断开，实测键电平后才接电机，不沿用旧示意图引脚。
 * 不包含原厂限位、防夹、堵转、WiFi、称重；原厂回滚镜像缺失。
 */
#include "motor_control.h"
sfr P0 = 0x80;
sfr P0M0 = 0x94;
sfr P0M1 = 0x93;
sfr P2 = 0xA0;
sfr P2M0 = 0x96;
sfr P2M1 = 0x95;
sfr P3 = 0xB0;
sfr P3M0 = 0xB2;
sfr P3M1 = 0xB1;
sfr P_SW1 = 0xA2;
sfr IE = 0xA8;
sfr AUXR = 0x8E;
sfr TMOD = 0x89;
sfr TCON = 0x88;
sfr TL0 = 0x8A;
sfr TH0 = 0x8C;
sfr TL1 = 0x8B;
sfr TH1 = 0x8D;
sfr SCON = 0x98;
sfr SBUF = 0x99;
sfr WDT_CONTR = 0xC1;
sbit MOTOR_BI = P2 ^ 0;
sbit MOTOR_FI = P2 ^ 2;
sbit KEY_SW1 = P2 ^ 6;
sbit KEY_SW2 = P0 ^ 2;
sbit KEY_SW3 = P2 ^ 7;
sbit TR0 = TCON ^ 4;
sbit TF0 = TCON ^ 5;
sbit TR1 = TCON ^ 6;
sbit RI = SCON ^ 0;
sbit TI = SCON ^ 1;
#define FOSC 11059200UL
#define T0_RELOAD (65536UL - (FOSC + 500UL) / 1000UL)
#define UART_RELOAD (65536UL - FOSC / 115200UL / 4UL)
volatile MotorControl control;
volatile unsigned char heartbeat;
unsigned char divider;
unsigned char read_pressed_keys(void)
{
    unsigned char keys = 0;
    /* 这些机械键另一端接地，读0才表示对应键按下。 */
    if (KEY_SW1 == 0) keys |= 1;
    if (KEY_SW2 == 0) keys |= 2;
    if (KEY_SW3 == 0) keys |= 4;
    return keys;
}
void motor_stop(void)
{
    /* 两路为低对应驱动停止/高阻；不等于机械已完全静止。 */
    MOTOR_FI = 0;
    MOTOR_BI = 0;
}
void timer0_isr(void) interrupt 1
{
    heartbeat++;
    divider++;
    if (divider == 10) {
        divider = 0;
        motor_control_tick(&control, read_pressed_keys());
        MOTOR_BI = 0;
        MOTOR_FI = control.running;
    }
}
void uart_text(const char huge *text)
{
    while (*text) {
        TI = 0;
        SBUF = *text++;
        /* TI==0表示未发完；Timer0中断仍然处理按键。 */
        while (TI == 0) { }
    }
}
void status(void)
{
    if (control.running) uart_text("MOTOR003 RUN ");
    else uart_text("MOTOR003 STOP ");
    uart_text("KEYS=");
    if (KEY_SW1) uart_text("1"); else uart_text("0");
    if (KEY_SW2) uart_text("1"); else uart_text("0");
    if (KEY_SW3) uart_text("1"); else uart_text("0");
    uart_text("\r\n");
}
void main(void)
{
    unsigned char value, previous_run, last_heartbeat;
    IE = 0;
    /* 先置低锁存值再切推挽；不重配其他应用引脚。 */
    motor_stop();
    P2M1 &= 0xFA;
    P2M0 |= 0x05;
    motor_control_init(&control);
    divider = 0;
    heartbeat = 0;
    previous_run = 0;
    last_heartbeat = 0;
    /* 三个键准双向输入并置1，使用弱上拉；不改变电机控制位。 */
    P0 |= 0x04;
    P0M0 &= 0xFB;
    P0M1 &= 0xFB;
    P2 |= 0xC0;
    P2M0 &= 0x3F;
    P2M1 &= 0x3F;
    /* UART1使用P3.0/RX、P3.1/TX，不用WiFi串口。 */
    P_SW1 &= 0x3F;
    P3 |= 0x03;
    P3M0 = (P3M0 & 0xFC) | 0x02;
    P3M1 = (P3M1 & 0xFC) | 0x01;
    TR0 = 0;
    TR1 = 0;
    TMOD = 0x00;                 /* T0/T1：16位自动重装、内部时钟。 */
    AUXR = (AUXR | 0xC0) & 0xFE; /* 1T，UART1以T1产生波特率。 */
    TH0 = (unsigned char)(T0_RELOAD >> 8);
    TL0 = (unsigned char)T0_RELOAD;
    TH1 = (unsigned char)(UART_RELOAD >> 8);
    TL1 = (unsigned char)UART_RELOAD;
    SCON = 0x50;                 /* UART：115200、8位、无校验、允许接收。 */
    TF0 = 0;
    TR1 = 1;
    TR0 = 1;
    IE = 0x82;                   /* 只开总中断与Timer0中断。 */
    WDT_CONTR = 0x33;            /* 看门狗约0.57s，复位后重新保持停机。 */
    uart_text("MOTOR003 BOOT STOP ANY KEY HOLD 3S\r\n");
    for (;;) {
        /* 主循环和定时器都推进才喂狗，避免扫描停滞后持续驱动。 */
        if (last_heartbeat != heartbeat) {
            last_heartbeat = heartbeat;
            WDT_CONTR = 0x33;
        }
        if (previous_run != control.running) {
            previous_run = control.running;
            status();
        }
        if (RI) {
            value = SBUF;
            RI = 0;
            if (value == '!') {
                /* 串口命令只停机、不允许启动，松手前禁止再触发。 */
                IE = 0;
                motor_control_stop(&control);
                motor_stop();
                IE = 0x82;
                status();
            } else if (value == '?') status();
        }
    }
}
