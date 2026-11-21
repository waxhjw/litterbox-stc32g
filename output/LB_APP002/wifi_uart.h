/* UART3 独立收发队列，Timer0 高优先级维持红外载波和保护节拍。 */
#ifndef WIFI_UART_H
#define WIFI_UART_H
#define WIFI_RELOAD(baud) ((unsigned int)(65536UL-FOSC/4UL/(baud)))
#define WIFI_QUEUE_MASK 0x7F
static volatile unsigned char edata wifi_rx[128], wifi_tx[128];
static unsigned char edata wifi_frame[64];
static volatile unsigned char rx_head, rx_tail, tx_head, tx_tail, tx_busy, rx_overflow;
static unsigned char wifi_size, wifi_sum, wifi_fast, wifi_fail, wifi_last_byte, reported_output;

static unsigned char app_output_now(void)
{
    return (unsigned char)(app_owner && guard.actual);
}

static void wifi_uart_baud(unsigned int reload)
{
    T4T3M=0x02;
    T3H=(unsigned char)(reload>>8);
    T3L=(unsigned char)reload;
    S3CON=0x50;
    T4T3M=0x0A;
    frame_step=0;
    rx_head=rx_tail;
}

#ifndef WIFI_UART_INTERRUPT
#define WIFI_UART_INTERRUPT interrupt 17
#endif
void uart3_isr(void) WIFI_UART_INTERRUPT
{
    unsigned char next, value;
    if (S3CON&1) {
        value=S3BUF;
        S3CON&=0xFE;
        next=(unsigned char)((rx_head+1)&WIFI_QUEUE_MASK);
        if (next!=rx_tail) {
            wifi_rx[rx_head]=value;
            rx_head=next;
        } else rx_overflow=1;
    }
    if (S3CON&2) {
        S3CON&=0xFD;
        if (tx_tail==tx_head) tx_busy=0;
        else {
            S3BUF=wifi_tx[tx_tail];
            tx_tail=(unsigned char)((tx_tail+1)&WIFI_QUEUE_MASK);
        }
    }
}

static void wifi_frame_data(unsigned char value)
{
    wifi_frame[wifi_size++]=value;
    wifi_sum+=value;
}

static void wifi_frame_start(unsigned char cmd, unsigned char length)
{
    wifi_size=0;
    wifi_sum=0;
    wifi_frame_data(0x55);
    wifi_frame_data(0xAA);
    wifi_frame_data(3);
    wifi_frame_data(cmd);
    wifi_frame_data(0);
    wifi_frame_data(length);
}

static unsigned char wifi_frame_end(void)
{
    unsigned char i, head=tx_head;
    wifi_frame_data(wifi_sum);
    if (((tx_tail-head-1)&WIFI_QUEUE_MASK)<wifi_size) {
        wifi_fail++;
        return 0;
    }
    /* 先写完一帧，再公布队尾。只有首字节启动使用临界区。 */
    for (i=0;i<wifi_size;i++) {
        wifi_tx[head]=wifi_frame[i];
        head=(unsigned char)((head+1)&WIFI_QUEUE_MASK);
    }
    IE=0;
    tx_head=head;
    if (!tx_busy) {
        tx_busy=1;
        S3BUF=wifi_tx[tx_tail];
        tx_tail=(unsigned char)((tx_tail+1)&WIFI_QUEUE_MASK);
    }
    IE=0x82;
    return 1;
}

static void wifi_product_info(void)
{
    static const char far info[]="{\"p\":\"0m0kpxctdshaigt9\",\"v\":\"0.2.0\",\"m\":0}";
    unsigned char i;
    wifi_frame_start(1,sizeof(info)-1);
    for (i=0;i<sizeof(info)-1;i++) wifi_frame_data(info[i]);
    wifi_frame_end();
}

static void wifi_service(void)
{
    unsigned char value, present;
    if (rx_overflow) {
        IE=0;
        rx_tail=rx_head;
        rx_overflow=0;
        IE=0x82;
        frame_step=0;
        link_errors++;
    }
    if (rx_tail!=rx_head) {
        value=wifi_rx[rx_tail];
        rx_tail=(unsigned char)((rx_tail+1)&WIFI_QUEUE_MASK);
        if ((unsigned char)(control_clock-wifi_last_byte)>10) frame_step=0;
        wifi_last_byte=control_clock;
        wifi_feed(value);
    }
    present=app_output_now();
    if (!app_start_pending && (dp_report_pending || present!=reported_output) &&
        ((tx_tail-tx_head-1)&WIFI_QUEUE_MASK)>=17 && wifi_report_state(present)) {
        dp_report_pending=0;
        reported_output=present;
    }
}
#endif
