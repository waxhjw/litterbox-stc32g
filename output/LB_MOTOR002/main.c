/*
 * LB_MOTOR002：STC32G8K64 + SS6285L + CLEAN机械按键诊断，非整机程序。
 * 用户明确授权：持续单方向转动，CLEAN长按3s启停，覆盖原厂程序。
 * 原理图1/3/6页：P2.0 -> BI，P2.1 -> FI，P0.4 -> KEY-CLEAN。
 * 按键低有效为本版配置；烧录时电机断开，实测按键电平后才接电机。
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
sbit MOTOR_FI = P2 ^ 1;
sbit KEY_CLEAN = P0 ^ 4;
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
        /* KEY_CLEAN==0才视为按下；机械状态与电平关系待实板核验。 */
        motor_control_tick(&control, KEY_CLEAN == 0);
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
    if (control.running) uart_text("MOTOR002 RUN ");
    else uart_text("MOTOR002 STOP ");
    if (KEY_CLEAN) uart_text("KEY=1\r\n");
    else uart_text("KEY=0\r\n");
}
void main(void)
{
    unsigned char value, previous_run, last_heartbeat;
    IE = 0;
    /* 先置低锁存值再切推挽；不重配其他应用引脚。 */
    motor_stop();
    P2M1 &= 0xFC;
    P2M0 |= 0x03;
    motor_control_init(&control);
    divider = 0;
    heartbeat = 0;
    previous_run = 0;
    last_heartbeat = 0;
    /* CLEAN准双向输入并置1，使用弱上拉；按下接地时读0。 */
    P0 |= 0x10;
    P0M0 &= 0xEF;
    P0M1 &= 0xEF;
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
    uart_text("MOTOR002 BOOT STOP CLEAN HOLD 3S\r\n");
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
