#include "tuya_link.h"

sfr P2=0xA0; sfr P2M0=0x96; sfr P2M1=0x95;
sfr P3=0xB0; sfr P3M0=0xB2; sfr P3M1=0xB1;
sfr P5=0xC8; sfr P5M0=0xCA; sfr P5M1=0xC9;
sfr P_SW1=0xA2; sfr P_SW2=0xBA;
sfr IE=0xA8; sfr AUXR=0x8E; sfr TMOD=0x89; sfr TCON=0x88;
sfr TL1=0x8B; sfr TH1=0x8D; sfr TL0=0x8A; sfr TH0=0x8C;
sfr T4T3M=0xDD; sfr T3H=0xD4; sfr T3L=0xD5;
sfr S3CON=0xAC; sfr S3BUF=0xAD;
sfr SCON=0x98; sfr SBUF=0x99; sfr WDT_CONTR=0xC1; sfr RSTCFG=0xFF;
sbit MOTOR_BI=P2^0; sbit MOTOR_FI=P2^2;
sbit TR0=TCON^4; sbit TF0=TCON^5; sbit TR1=TCON^6;
sbit RI=SCON^0; sbit TI=SCON^1;

#define FOSC 11059200UL
#define RELOAD(baud) ((unsigned int)(65536UL-FOSC/4UL/(baud)))

/* 本产品的开发 PID，仅用于猫砂盆，WBR3 的模组固件和授权保持原样。 */
static const char far product_info[]="{\"p\":\"0m0kpxctdshaigt9\",\"v\":\"0.1.1\",\"m\":0}";
static unsigned char wifi_tx_sum, tried_fast, tx_fail, rx_age;

static void wifi_uart_baud(unsigned int reload)
{
    T4T3M=0x02; /* T3 停止，使用 1T 定时。 */
    T3H=(unsigned char)(reload>>8);
    T3L=(unsigned char)reload;
    S3CON=0x50; /* 8 位，允许接收，Timer3 发生波特率。 */
    T4T3M=0x0A;
    frame_step=0;
}

static void wifi_uart_send(unsigned char value)
{
    unsigned int wait=50000U;
    S3CON&=0xFD;
    S3BUF=value;
    while ((S3CON&2)==0 && --wait) { }
    if (wait==0) tx_fail++;
}

static void wifi_frame_data(unsigned char value)
{
    wifi_tx_sum+=value;
    wifi_uart_send(value);
}

static void wifi_frame_start(unsigned char cmd, unsigned char length)
{
    wifi_tx_sum=0;
    wifi_frame_data(0x55);
    wifi_frame_data(0xAA);
    wifi_frame_data(3);
    wifi_frame_data(cmd);
    wifi_frame_data(0);
    wifi_frame_data(length);
}

static void wifi_frame_end(void) { wifi_uart_send(wifi_tx_sum); }

static void wifi_product_info(void)
{
    unsigned char i;
    wifi_frame_start(1,sizeof(product_info)-1);
    for (i=0;i<sizeof(product_info)-1;i++) wifi_frame_data(product_info[i]);
    wifi_frame_end();
}

static void debug_char(unsigned char c)
{
    TI=0;
    SBUF=c;
    while (TI==0) { }
}

static void debug_text(const char far *s)
{
    while (*s) debug_char(*s++);
}

static void debug_hex(unsigned char n)
{
    n&=15;
    debug_char(n<10 ? n+'0' : n+'A'-10);
}

static void debug_field(unsigned char tag, unsigned char n)
{
    debug_char(' ');
    debug_char(tag);
    debug_char('=');
    debug_hex(n>>4);
    debug_hex(n);
}

static void debug_status(void)
{
    debug_text("WIFI002");
    debug_field('B', tried_fast);
    debug_field('N', link_network);
    debug_field('H', link_heartbeat);
    debug_field('P', link_product);
    debug_field('M', link_mode);
    debug_field('S', link_net_reports);
    debug_field('A', link_pair);
    debug_field('Q', link_query);
    debug_field('D', link_dp);
    debug_field('E', link_errors);
    debug_field('T', tx_fail);
    debug_field('O', P2&5);
    debug_field('I', dp_last_id);
    debug_field('U', dp_last_value);
    debug_field('V', dp_paused);
    debug_field('K', dp_changes);
    debug_field('R', dp_reports);
    debug_field('X', dp_invalid);
    debug_text("\r\n");
}

void main(void)
{
    unsigned char value;
    IE=0;
    /* 联网台架保持两路电机指令低，全程没有置高路径。 */
    MOTOR_BI=0; MOTOR_FI=0;
    P2M1&=0xFA; P2M0|=5;
    RSTCFG=(RSTCFG&0xBC)|0x41;

    /* UART1 在 CH340，WBR3 EN（P3.6）保持高阻，由模块内部上拉。 */
    P_SW1&=0x3F;
    P3|=3; P3M0=(P3M0&0xBC)|2; P3M1=(P3M1&0xFC)|0x41;
    AUXR=0x40; TMOD=0; SCON=0x50;
    TH1=(unsigned char)(RELOAD(115200UL)>>8); TL1=(unsigned char)RELOAD(115200UL);
    TR1=1; TF0=0; TR0=1; /* Timer0 约 71ms 溢出，用于截断不完整帧。 */

    /* UART3 切到 P5.0 RX 与 P5.1 TX，生产板 Q2/Q3 完成电平转换。 */
    P_SW2|=2;
    P5|=3; P5M0=(P5M0&0xFC)|2; P5M1=(P5M1&0xFC)|1;
    wifi_uart_baud(RELOAD(9600UL));
    WDT_CONTR=0x33;
    for (;;) {
        WDT_CONTR=0x33;
        if (S3CON&1) {
            value=S3BUF;
            S3CON&=0xFE;
            rx_age=0;
            wifi_feed(value);
        }
        if (TF0) {
            TF0=0;
            if (frame_step && ++rx_age>=2) {
                frame_step=0;
                link_errors++;
            }
        }
        if (RI) {
            value=SBUF;
            RI=0;
            if (value=='p') wifi_pair();
            else if (value=='b' && !link_heartbeat) {
                tried_fast^=1;
                wifi_uart_baud(tried_fast ? RELOAD(115200UL) : RELOAD(9600UL));
            } else if (value!='?') continue;
            debug_status();
        }
    }
}
