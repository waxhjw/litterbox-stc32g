"""编译真实固件的array_main.c；只把C251寄存器/串口/ADC换成主机模型，不连接硬件。
覆盖：窗口内峰值采样、连续N窗确认、未采样窗口不参与判定、ADC超时不当成收到光、
载波开关清判定、状态串格式，以及3秒长按节拍。

节拍回归的反证不靠历史版本源码（IR009的源已被同步成修正值，无法复现），
改用变异测试：把TICK_HALF_PER_100US强行改回IR008的8200，要求同一套断言必须失败。
只有"改坏了能报错"的测试才算真的在测这个常数。
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
profile = sys.argv[1] if len(sys.argv) > 1 else 'IR010'
app_profile = profile in ('APP001', 'APP002', 'APP003', 'APP004', 'APP005')
source = root / 'diagnostics' / profile / 'array_main.c'
native = source.read_text(encoding='utf-8')
native = re.sub(r'sfr P0=.*?(?=#define XREG)', '', native, flags=re.S)
native = re.sub(r'#define XREG\(addr\).*', '#define XREG(addr) xfr[(addr)&255]', native)
native = native.replace(' interrupt 1', '').replace('void main(void)', 'void firmware_main(void)')
native = native.replace('volatile bit ', 'volatile unsigned char ')
native = re.sub(r'^bit ', 'unsigned char ', native, flags=re.M)

preamble = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define far
#ifdef APP001
#define edata
#define WIFI_UART_INTERRUPT
static unsigned char IE2,IP,S3CON,S3BUF,T4T3M,T3H,T3L;
#endif
typedef union { unsigned char byte; struct { unsigned char b0:1,b1:1,b2:1,b3:1,b4:1,b5:1,b6:1,b7:1; } bit; } Port;
static Port p0,p1,p2,p3,p5;
#ifdef IR017
static Port p4;
static unsigned char P4M0,P4M1;
#define P4 p4.byte
#endif
#define P0 p0.byte
#define P1 p1.byte
#define P2 p2.byte
#define P3 p3.byte
#define P5 p5.byte
#define KEY1 p2.bit.b6
#define KEY2 p0.bit.b2
#define KEY3 p2.bit.b7
#define MOTOR_BI p2.bit.b0
#define MOTOR_FI p2.bit.b2
#define ARRAY_TX1 p0.bit.b4
#define ARRAY_TX2 p5.bit.b2
#define ARRAY_TX3 p5.bit.b3
static unsigned char P0M0,P0M1,P1M0,P1M1,P2M0,P2M1,P3M0,P3M1,P5M0,P5M1;
static unsigned char P_SW1,P_SW2,IE,AUXR,TMOD,TL0,TH0,TL1,TH1,SCON,SBUF,WDT_CONTR,RSTCFG;
static unsigned char TR0,TF0,TR1,RI,ADC_RES,ADC_RESL,ADCCFG,xfr[256];
static unsigned char adc_register, ti_register=1;
static unsigned char sim_high=1, sim_timeout=0;
#ifdef IR013
static unsigned char dark_channels, sim_disconnected;
#endif
static char serial_out[16384];
static unsigned int serial_used;
/* 模拟"ADC转换耗时"造成的窗口翻页：真实芯片一次转换约100us，主循环一轮3次
 * 转换之间随时可能翻进下一个窗口。hook在第hook_at次转换时触发一次，
 * 由测试用例决定在哪一刻把窗口推过去。 */
static void (*adc_hook)(void);
static unsigned int adc_calls, hook_at;
static unsigned char *mock_adc(void) {
    if ((adc_register&0x40) && sim_timeout==0) {
        unsigned short value = sim_high ? 0x0F00 : 0x03C0;
#ifdef IR013
        unsigned char channel=adc_register&15;
        if (dark_channels & (channel==14 ? 1 : (2u<<channel))) value=0x03C0;
        if (sim_disconnected) value=0x0FFF;
#endif
        ADC_RES=(unsigned char)(value>>8); ADC_RESL=(unsigned char)value;
        adc_register=(adc_register&0xbf)|0x20;
        adc_calls++;
        if (adc_hook && adc_calls==hook_at) { void (*h)(void)=adc_hook; adc_hook=0; h(); }
    }
    return &adc_register;
}
static unsigned char *mock_ti(void) {
    if (ti_register==0) {
        assert(serial_used+1<sizeof(serial_out));
        serial_out[serial_used++]=(char)SBUF; serial_out[serial_used]=0; ti_register=1;
    }
    return &ti_register;
}
#define ADC_CONTR (*mock_adc())
#define TI (*mock_ti())
'''

tests = r'''
static void prepare(void) {
    P0=0xff; P1=0xff; P2=0xfc; P3=0xff; P5=0xff;
    P0M0=0; P0M1=0x50; P5M0=0; P5M1=0x0c;
    motor_control_init(&control); motor_ir_guard_init(&guard);
    ir_carrier_init(&carrier); ir_beam_init(&beam);
    divider=0; tick_half=0; heartbeat=0; RSTCFG=0x51;
    sim_high=1; sim_timeout=0; adc_register=0;
    serial_used=0; serial_out[0]=0; ti_register=1;
    adc_calls=0; adc_hook=0; hook_at=0;
}
/* 把当前窗口推到结束（close按已落地的轮次结算），再推进到下一个窗口开始
 * （open清零peak/sampled并把gen加一）。用来模拟ADC耗时导致采样跨窗。 */
static void flip_window(void) {
    int n=0;
    while(beam.in_window && n++<4000) timer0_isr();
    n=0;
    while(!beam.in_window && n++<4000) timer0_isr();
    assert(beam.in_window==1);
}
/* 推进中断直到载波窗口打开/关闭，验证ISR边界判定本身。 */
static void window_open(void) { int n=0; while(!beam.in_window && n++<4000) timer0_isr(); assert(beam.in_window==1); }
static void window_close(void) { int n=0; while(beam.in_window && n++<4000) timer0_isr(); assert(beam.in_window==0); }
static void run_window(int sample) { window_open(); if(sample) sample_window(); window_close(); }

int main(void) {
    unsigned int i; int w;

    /* 1) 载波开：6个窗口都有光，判定为全通，峰值就是亮态。 */
    prepare(); handle_command('c');
    assert(strstr(serial_out,"C=1"));
    for(w=0;w<6;w++) run_window(1);
    assert(beam.blocked==0);
    assert(beam.miss[0]==0 && beam.miss[1]==0 && beam.miss[2]==0);
    assert(beam.peak[0]==0x0F00 && beam.peak[1]==0x0F00 && beam.peak[2]==0x0F00);

    /* 2) 三路同时遮挡：前3窗不判定，第4窗才确认，位图为7。 */
    sim_high=0;
    for(w=0;w<3;w++) run_window(1);
    assert(beam.blocked==0 && beam.miss[0]==3);
    run_window(1);
    assert(beam.blocked==7 && beam.miss[2]==4);

    /* 3) 恢复光照：一个窗口就解除遮挡并清零计数。 */
    sim_high=1; run_window(1);
    assert(beam.blocked==0 && beam.miss[0]==0);

    /* 4) 主循环忙、没采样的窗口不参与判定，不能自己涨成遮挡。 */
    prepare(); handle_command('c'); sim_high=0;
    for(w=0;w<8;w++) run_window(0);
    assert(beam.blocked==0 && beam.miss[0]==0);

    /* 5) ADC超时0xFFFF不能被当成"收到光"，仍应按遮挡累计。 */
    prepare(); handle_command('c'); sim_timeout=1;
    for(w=0;w<4;w++) run_window(1);
    assert(beam.blocked==7);

    /* 6) 关载波不采样；再开载波清掉上一轮判定。 */
    handle_command('k'); assert(strstr(serial_out,"C=0"));
    handle_command('c');
    assert(beam.blocked==0 && beam.in_window==0 && beam.fresh==0);

    /* 7) 状态串格式。 */
    prepare(); handle_command('?');
    assert(strstr(serial_out,"IR9 S K=111 R=0051 Q=0 C=0 B=0"));

    /* 8) 3秒长按节拍：一拍=8半周期×100分频=800次中断≈10.5ms。
     *    300拍≈3.15s；IR008写成8200时这里需要2400万次中断才成立。 */
    prepare();
    for(i=0;i<2000u;i++) timer0_isr();          /* 先松手，armed建立 */
    KEY3=0;
    for(i=0;i<241000u;i++) timer0_isr();
    assert(control.running==1 && MOTOR_FI==1);
    assert(guard.armed==0);                      /* 未知采样不建立光路保护 */
    KEY3=1;
    for(i=0;i<2000u;i++) timer0_isr();           /* 松手才能再次触发 */
    KEY3=0;
    for(i=0;i<241000u;i++) timer0_isr();
    assert(control.running==0 && MOTOR_FI==0);

    /* 9) IR010现场翻车的那个场景：主循环被报告打印占住，轮到采样时窗口只剩尾巴。
     *    门闸必须挡住，整窗不采；sampled保持0，close不结算，绝不用半窗暗态去结账。 */
    prepare(); handle_command('c'); sim_high=0;
    window_open();
    assert(carrier.burst_ticks==BURST_HALF);
    assert(ir_beam_ready(&beam, carrier.burst_ticks)==1);   /* 窗口刚开：该采 */
    while(carrier.burst_ticks>30) timer0_isr();             /* 拖到窗口后段 */
    assert(carrier.burst_ticks<=30 && carrier.burst_ticks>0);
    assert(ir_beam_ready(&beam, carrier.burst_ticks)==0);   /* 只剩尾巴：不许采 */
    assert(beam.sampled==0);
    window_close();
    assert(beam.miss[0]==0 && beam.miss[1]==0 && beam.miss[2]==0 && beam.blocked==0);

    /* 9b) 反过来：窗口刚开始就采，两轮全部落在窗内，峰值有效、sampled置位。 */
    prepare(); handle_command('c');
    window_open();
    sample_window();
    assert(beam.sampled==1);
    assert(beam.peak[0]==0x0F00 && beam.peak[1]==0x0F00 && beam.peak[2]==0x0F00);
    window_close();
    assert(beam.miss[0]==0 && beam.blocked==0);

    /* 11) 采样中途跨窗（IR011现场翻车的真实机制）：一轮3次ADC约300us，
     *     转换之间窗口随时可能翻页。此时这一轮的读数分属两个不同窗口，
     *     一个都不许落地；旧窗口因没采成不结算，新窗口峰值必须干净。 */
    prepare(); handle_command('c');
    window_open();
    {
        unsigned char g0=beam.gen;
        adc_calls=0; hook_at=1; adc_hook=flip_window;   /* 第1次转换后立刻翻页 */
        sample_window();
        assert(beam.gen==(unsigned char)(g0+1));        /* 窗口确实翻了一页 */
    }
    assert(beam.sampled==0);                            /* 整轮作废 */
    assert(beam.peak[0]==0 && beam.peak[1]==0 && beam.peak[2]==0);
    assert(beam.last[0]==0 && beam.last[1]==0 && beam.last[2]==0);
    assert(beam.miss[0]==0 && beam.miss[1]==0 && beam.miss[2]==0);

    /* 11b) 第1轮已落地、第2轮才开始跨窗：旧窗口按已落地的第1轮正常结算，
     *      第2轮整轮丢弃，新窗口不得沾到任何暗态。这一条正是IR011把
     *      miss 一路涨到3却永远到不了4的原因 —— 暗态被记到了下一窗账上。 */
    prepare(); handle_command('c');
    window_open();
    {
        unsigned char g0=beam.gen;
        adc_calls=0; hook_at=4; adc_hook=flip_window;   /* 第2轮第1次转换后翻页 */
        sample_window();
        assert(beam.gen==(unsigned char)(g0+1));
    }
    assert(beam.sampled==0);
    assert(beam.peak[0]==0 && beam.peak[1]==0 && beam.peak[2]==0);
    assert(beam.last[0]==0x0F00);                       /* 旧窗口用第1轮结算，快照有效 */
    assert(beam.miss[0]==0 && beam.miss[1]==0 && beam.miss[2]==0);
    assert(beam.blocked==0);

    /* 10) 停止命令仍然清电机与输出。 */
    prepare(); control.running=1; guard.actual=1; MOTOR_FI=1;
    handle_command('!');
    assert(control.running==0 && guard.actual==0 && MOTOR_FI==0 && MOTOR_BI==0);

    puts("PASS: real firmware window peak sampling, 4-window confirm, unsampled-window skip, cross-window round discard, settlement snapshot, ADC timeout, carrier restart, status, 3s long-press tick");
    return 0;
}
'''

linked_tests = r'''
/* 推进真实ISR，按主循环入口采样和切换载波，电机端口使用主机寄存器模型。 */
static void ticks(unsigned int count, unsigned char sample)
{
    unsigned long n, interrupts=(unsigned long)count*760;
    for(n=0; n<interrupts; n++) {
        timer0_isr();
        update_carrier();
        if(sample && carrier.mode && ir_beam_ready(&beam, carrier.burst_ticks)) sample_window();
    }
}

static void prepare(void)
{
    P0=0xff; P2=0xfc; RSTCFG=0x51; IE=0x82;
#ifdef IR016
    P1=0x20;
#endif
    ADC_CONTR=0; adc_calls=0; adc_hook=0;
    sim_high=1; sim_timeout=0; dark_channels=0; sim_disconnected=0;
    serial_used=0; serial_out[0]=0;
    motor_tick=0; motor_test=0; carrier_requested=0;
#ifdef IR017
    /* 模型重开时模拟 C 启动代码清零；其余按键初值与固件入口相同。 */
    control=(MotorControl){0};
    control.candidate=1;
    control.stable_pressed=1;
    radar_idle=0;
    P4=0;
    handle_command('H');
#else
    motor_control_init(&control);
#endif
#ifdef APP001
    dp_paused=0; dp_manual_level=0; app_start_pending=0; app_owner=0; app_remaining=0;
#ifdef APP003
    control_report=0; link_network=4; dp_report_pending=0; reported_control=0xFF;
    rx_head=rx_tail=tx_head=tx_tail=tx_busy=0;
#endif
#endif
    motor_ir_guard_init(&guard);
    ir_carrier_stop(&carrier); ir_beam_init(&beam);
    serial_used=0; serial_out[0]=0;
    ticks(3,0);
}

static void start_key(void)
{
    KEY1=0;
    ticks(298,1);
    assert(control.running==0 && MOTOR_FI==0);
    ticks(4,1);
    assert(control.running==1);
    KEY1=1;
    ticks(2,1);
}

static void close_window(void)
{
    while(beam.in_window) timer0_isr();
}

int main(void)
{
    unsigned char mask;
    prepare();
    handle_command('?');
#if defined(IR017)
    assert(strstr(serial_out, "IRC S K=111 R=0051 Q=0 C=0 B=0 D=0"));
#elif defined(IR016)
    assert(strstr(serial_out, "IRB S K=111 R=0051 Q=0 C=0 B=0"));
#else
    assert(strstr(serial_out, "IRA S K=111 R=0051 Q=0 C=0 B=0"));
#endif
#ifdef IR014
    P1=0x00;
    handle_command('h');
    P1=0x20;
    handle_command('h');
    P1=0x40;
    handle_command('h');
    P1=0x60;
    handle_command('h');
    assert(strstr(serial_out, "H0\r\nH1\r\nH2\r\nH3\r\n"));
    assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);
#ifdef IR015
    {
        unsigned int before=serial_used;
        handle_command(0x7f);
        handle_command(0x46);
        handle_command(0xb9);
        assert(serial_used==before);
        assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);
    }
#endif
#endif
    handle_command('c');
    timer0_isr();
    assert(beam.in_window && carrier.burst_ticks==BURST_HALF);
    hook_at=adc_calls+1;
    adc_hook=close_window;
    sample_window();
    assert(beam.in_window==0 && beam.sampled==0);
    handle_command('k');
    assert(carrier.mode==0);

#ifdef IR016
    /* 双高拒绝，补磁后按住不触发。松手重按才建立请求。 */
    prepare(); P1=0x60; KEY1=0;
    ticks(310,1);
    assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);
    P1=0x20;
    ticks(20,1);
    assert(control.running==0 && MOTOR_FI==0);
    KEY1=1; ticks(2,1);
    start_key();
    assert(MOTOR_FI==0 && carrier.mode==1);
    /* 初次起转前霍尔释放，取消请求，随后补磁也不自动启动。 */
    P1=0x60; ticks(1,1);
    assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);
    P1=0x40; ticks(IR_RESUME_TICKS+3,1);
    assert(MOTOR_FI==0);

    /* 电机诊断模式也核对霍尔，分别覆盖一路低和双低。 */
    for(mask=0; mask<3; mask++) {
        prepare(); P1=(unsigned char)(mask<<5);
        handle_command('m');
        start_key();
        assert(MOTOR_FI==1 && carrier.mode==0);
        handle_command('!');
    }
    prepare(); P1=0x60;
    handle_command('m'); KEY1=0;
    ticks(310,1);
    assert(control.running==0 && MOTOR_FI==0);
#endif

#ifdef IR017
    /* 极性未确认时禁止开始。实测高有效时，待机高拒绝长按。 */
    prepare(); radar_idle=0; KEY1=0;
    ticks(310,1);
    assert(control.running==0 && MOTOR_FI==0);
    KEY1=1; ticks(3,1); handle_command('H');
    P4=0x80; KEY1=0;
    ticks(310,1);
    assert(control.running==0 && MOTOR_FI==0);
    P4=0;
    ticks(10,1);
    assert(control.running==0 && MOTOR_FI==0);
    KEY1=1; ticks(3,1); start_key();
    ticks(IR_RESUME_TICKS,1);
    assert(MOTOR_FI==1 && carrier.mode==1);
    handle_command('L'); /* 运行时忽略重新设置极性。 */
    P4=0x80; ticks(1,1);
    assert(MOTOR_FI==0 && MOTOR_BI==0 && control.running==0 && carrier.mode==0);
    handle_command('?');
    assert(strstr(serial_out, "IRC S K=111 R=0051 Q=0 C=0 B=0 D=1"));
    P4=0; ticks(IR_RESUME_TICKS+1,1);
    assert(MOTOR_FI==0 && control.running==0);

    /* 等待红外期间，雷达触发取消请求；低有效还会覆盖独立台架模式。 */
    prepare(); start_key(); P4=0x80; ticks(1,1);
    assert(MOTOR_FI==0 && control.running==0 && carrier.mode==0);
    prepare(); P4=0x80; handle_command('L'); handle_command('m'); start_key();
    assert(MOTOR_FI==1 && carrier.mode==0);
    P4=0; ticks(1,1);
    assert(MOTOR_FI==0 && control.running==0 && motor_test==0);
#endif

    /* 正常运行请求必须等光路有效，随后任一路确认遮挡都要暂停。 */
    prepare();
    start_key();
    assert(carrier.mode==1 && MOTOR_FI==0 && MOTOR_BI==0);
    ticks(IR_RESUME_TICKS,1);
    assert(MOTOR_FI==1);
#ifdef IR016
    /* 起转后可离开霍尔。其后的红外暂停和恢复也在双高条件下验证。 */
    P1=0x60;
    ticks(1,1);
    assert(MOTOR_FI==1);
#endif
    for(mask=1; mask<=4; mask<<=1) {
        dark_channels=mask;
        ticks(6,1);
        assert(beam.blocked==mask && MOTOR_FI==0 && carrier.mode==1 && control.running==1);
        handle_command('k');
        assert(carrier.mode==1);
        dark_channels=0;
        ticks(1,1);
        assert(guard.clear_ticks_left==IR_RESUME_TICKS-1);
        ticks(IR_RESUME_TICKS-2,1);
        assert(guard.clear_ticks_left==1 && MOTOR_FI==0);
        ticks(1,1);
        assert(guard.clear_ticks_left==0 && MOTOR_FI==1);
    }

    /* 丢样和重挡都必须重新计时，手动停机取消等待。 */
    ticks(6,0);
    assert(MOTOR_FI==0);
    ticks(300,1);
    dark_channels=2;
    ticks(6,1);
    assert(guard.clear_ticks_left==IR_RESUME_TICKS);
    dark_channels=0;
    KEY3=0;
    ticks(302,1);
    assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);
    ticks(IR_RESUME_TICKS,1);
    assert(MOTOR_FI==0);

    /* 上路已经被遮挡才长按启动时，等待窗口内也不得产生一次短暂输出。 */
    prepare();
    dark_channels=4;
    start_key();
    assert(MOTOR_FI==0 && carrier.mode==1);
    {
        unsigned int elapsed;
        for(elapsed=0; elapsed<IR_RESUME_TICKS+5; elapsed++) {
            ticks(1,1);
            assert(MOTOR_FI==0);
        }
    }
    assert(beam.blocked==4 && guard.clear_ticks_left==IR_RESUME_TICKS);
    dark_channels=0;
    ticks(1,1);
    assert(guard.clear_ticks_left==IR_RESUME_TICKS-1);
    ticks(IR_RESUME_TICKS-2,1);
    assert(MOTOR_FI==0);
    ticks(1,1);
    assert(MOTOR_FI==1);
    handle_command('!');

    /* 接收线断开时，模拟三路满量程，正常模式不允许运行。 */
    prepare();
    sim_disconnected=1;
    start_key();
    ticks(IR_RESUME_TICKS+6,1);
    assert(MOTOR_FI==0 && beam.blocked==7);
    handle_command('!');
    assert(control.running==0 && MOTOR_FI==0 && carrier.mode==0);

    /* 独立电机台架模式必须显式选择，停机自动退出。 */
    prepare();
    handle_command('m');
    start_key();
    assert(MOTOR_FI==1 && carrier.mode==0);
    handle_command('0');
    assert(control.running==0 && MOTOR_FI==0 && motor_test==0);
#ifdef APP001
    /* 校验损坏的下发报文不能启动，正常报文驱动控制并回报实际输出。 */
    prepare(); P1=0x20;
    {
        const unsigned char frame[]={0x55,0xAA,0,6,0,5,1,1,0,1,1,0x0E};
        unsigned char i;
        for (i=0;i<sizeof(frame)-1;i++) wifi_feed(frame[i]);
        wifi_feed(0);
        ticks(2,1);
        assert(link_errors!=0 && control.running==0);
        for (i=0;i<sizeof(frame);i++) wifi_feed(frame[i]);
        ticks(2,1);
        assert(control.running==1 && app_owner==1 && MOTOR_FI==0);
#ifdef APP003
        wifi_service();
#ifdef APP004
        assert(tx_head==29 && wifi_tx[3]==7 && wifi_tx[5]==10);
        assert(wifi_tx[20]==7 && wifi_tx[22]==5);
        assert(wifi_tx[23]==22 && wifi_tx[24]==4 && wifi_tx[26]==1 && wifi_tx[27]==2);
#else
        assert(tx_head==22 && wifi_tx[3]==7 && wifi_tx[5]==15);
        assert(wifi_tx[16]==22 && wifi_tx[17]==4 && wifi_tx[19]==1 && wifi_tx[20]==2);
#endif
        assert(wifi_tx[6]==1 && wifi_tx[11]==5 && wifi_tx[15]==0);
#ifdef APP005
        assert(wifi_tx[10]==1 && MOTOR_FI==0); /* 确认请求，实际工作仍为等待。 */
#else
        assert(wifi_tx[10]==0);
#endif
#endif
        ticks(IR_RESUME_TICKS,1);
        assert(MOTOR_FI==1);
        wifi_service();
#ifdef APP003
#ifdef APP004
        assert(tx_head==58 && wifi_tx[39]==1 && wifi_tx[56]==3);
        P4=0x80; ticks(1,1);
        wifi_service();
        assert(tx_head==87 && wifi_tx[68]==0 && wifi_tx[85]==0);
#else
        assert(tx_head==44 && wifi_tx[32]==1 && wifi_tx[42]==3);
        P4=0x80; ticks(1,1);
        wifi_service();
        assert(tx_head==66 && wifi_tx[54]==0 && wifi_tx[64]==0);
#endif
#else
        assert(tx_head==17 && wifi_tx[3]==7 && wifi_tx[6]==1 && wifi_tx[10]==1);
        assert(wifi_tx[11]==5 && wifi_tx[15]==0);
#endif
    }

    /* 霍尔不就绪时，App请求拒绝；补磁也不重新触发同一个高值。 */
    prepare(); P1=0x60;
    frame_len=5; dp_payload[0]=1; dp_payload[1]=1; dp_payload[2]=0; dp_payload[3]=1; dp_payload[4]=1;
    wifi_handle_dp(); ticks(2,1);
    assert(control.running==0 && MOTOR_FI==0 && app_owner==0);
    P1=0x20; wifi_handle_dp(); ticks(2,1);
    assert(control.running==0);
    dp_payload[4]=0; wifi_handle_dp();
    dp_payload[4]=1; wifi_handle_dp(); ticks(2,1);
    assert(control.running==1 && app_owner==1 && MOTOR_FI==0 && carrier.mode==1);
    ticks(IR_RESUME_TICKS,1);
    assert(MOTOR_FI==1);
#ifdef APP003
#ifdef APP005
    assert(control_report==(DP_CLEANING | DP_MANUAL_ACCEPTED));
#else
    assert(control_report==(DP_CLEANING | DP_APP_OUTPUT));
#endif
#else
    assert(app_output_now()==1);
#endif
    dp_payload[0]=5; wifi_handle_dp(); ticks(1,1);
    assert(MOTOR_FI==0 && app_owner==1 && control.running==1);
#ifdef APP003
#ifdef APP005
    assert(control_report==(DP_WAITING | DP_PAUSE_APPLIED | DP_MANUAL_ACCEPTED));
#else
    assert(control_report==(DP_WAITING | DP_PAUSE_APPLIED));
#endif
#endif
    dp_payload[4]=0; wifi_handle_dp(); ticks(1,1);
    assert(MOTOR_FI==1);
    dark_channels=2; ticks(6,1);
    assert(MOTOR_FI==0 && app_owner==1);
    dark_channels=0; ticks(IR_RESUME_TICKS+2,1);
    assert(MOTOR_FI==1);
    P4=0x80; ticks(1,1);
    assert(MOTOR_FI==0 && app_owner==0 && control.running==0);
    P4=0; wifi_handle_dp(); ticks(3,1);
    assert(MOTOR_FI==0 && control.running==0);

    /* App 超过台架等待/运行上限撤销，未放行之前保持停止。 */
    prepare(); dark_channels=4;
    dp_payload[0]=1; dp_payload[4]=1; wifi_handle_dp();
    ticks(APP_TRIAL_TICKS-2,1);
    assert(app_owner==1 && control.running==1 && MOTOR_FI==0);
    ticks(3,1);
    assert(app_owner==0 && control.running==0 && MOTOR_FI==0);
    puts("PASS: App manual request, shared Hall/IR/radar gates, pause/continue and bounded trial");
#endif
    puts("PASS: IR013 startup, three independent beam holds, 10s boundary, reblock, stale data, manual cancel and independent motor test");
    return 0;
}
'''

TICK_LINE = re.compile(r'#define TICK_HALF_PER_100US\s+\d+U')


def build(folder, tag, tick=None):
    """编译一份可执行：tick=None 用源码原值；否则强制替换节拍常数做变异测试。"""
    text = native
    if tick is not None and (app_profile or profile in ('IR013', 'IR014', 'IR015', 'IR016', 'IR017')):
        text, n = re.subn(r'#define MOTOR_CONTROL_TICKS .*', f'#define MOTOR_CONTROL_TICKS {tick}U', text)
        assert n == 1
    elif tick is not None:
        text, n = TICK_LINE.subn(f'#define TICK_HALF_PER_100US {tick}U', text)
        assert n == 1, f'变异测试找不到TICK_HALF_PER_100US定义，替换了{n}处'
    unit = folder / f'test_{tag}.c'
    linked = app_profile or profile in ('IR013', 'IR014', 'IR015', 'IR016', 'IR017')
    flags = '#define IR013\n' if linked else ''
    if app_profile or profile in ('IR014', 'IR015', 'IR016', 'IR017'):
        flags += '#define IR014\n'
    if app_profile or profile in ('IR015', 'IR016', 'IR017'):
        flags += '#define IR015\n'
    if app_profile or profile in ('IR016', 'IR017'):
        flags += '#define IR016\n'
    if app_profile or profile == 'IR017':
        flags += '#define IR017\n'
    if app_profile:
        flags += '#define APP001\n'
    if profile in ('APP003', 'APP004', 'APP005'):
        flags += '#define APP003\n'
    if profile in ('APP004', 'APP005'):
        flags += '#define APP004\n'
    if profile == 'APP005':
        flags += '#define APP005\n'
    unit.write_text(flags + preamble + text +
                    (linked_tests if linked else tests), encoding='utf-8')
    exe = folder / f'test_{tag}.exe'
    subprocess.run(['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-I', str(source.parent), str(unit), '-o', str(exe)], check=True)
    return exe


with tempfile.TemporaryDirectory(prefix='ir-beam-host-', dir=root/'build') as folder:
    folder = Path(folder)

    # 1) 真源码必须全绿。
    real = build(folder, 'real', None)
    done = subprocess.run([str(real)], capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    assert done.returncode == 0, f'真源码断言失败 rc={done.returncode}\n{done.stderr}'

    # 2) 变异测试：把节拍改回IR008的8200，3秒长按断言必须失败，
    #    否则说明这组断言根本没在约束那个常数（也就是IR009当初意外PASS的原因）。
    mutant = build(folder, 'mutant', 8200)
    broken = subprocess.run([str(mutant)], capture_output=True, text=True)
    assert broken.returncode != 0, '把节拍改回8200后仍然PASS，说明长按断言失效，测试无意义'
    assert 'Assertion' in broken.stderr or 'assert' in broken.stderr.lower(), \
        f'变异版失败原因不是断言: {broken.stderr}'

    print(f'PASS: {profile} 真源码全绿；把TICK_HALF_PER_100US改成8200后长按断言如期失败（回归可复现）')
