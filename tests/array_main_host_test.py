"""编译真实array_main.c函数；仅替换C251寄存器/串口/ADC为主机模型，不连接硬件。"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
source=root/'diagnostics/IR006/array_main.c'
native=source.read_text(encoding='utf-8')
native=re.sub(r'sfr P0=.*?(?=#define XREG)', '',native,flags=re.S)
native=re.sub(r'#define XREG\(addr\).*', '#define XREG(addr) xfr[(addr)&255]',native)
native=native.replace(' interrupt 1','').replace('void main(void)','void firmware_main(void)')
preamble=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define far
typedef union { unsigned char byte; struct { unsigned char b0:1,b1:1,b2:1,b3:1,b4:1,b5:1,b6:1,b7:1; } bit; } Port;
static Port p0,p1,p2,p3,p5;
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
static unsigned char adc_register,ti_register=1;
static int adc_timeout;
static unsigned int conversions[16];
static char serial_out[16384];
static unsigned int serial_used;
static unsigned char *mock_adc(void) {
    if ((adc_register&0x40) && adc_timeout==0) {
        unsigned char channel=adc_register&15;
        unsigned short value=channel==14 ? 0xabc : channel==0 ? 0x123 : 0xfff;
        conversions[channel]++;
        if (conversions[channel]&1) value=0x032; /* 每路首个转换模拟旧采样电荷。 */
        ADC_RES=(unsigned char)(value>>8); ADC_RESL=(unsigned char)value;
        adc_register=(adc_register&0xbf)|0x20;
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
tests=r'''
static void prepare(void) {
    P0=0xff; P1=0xff; P2=0xfc; P3=0xff; P5=0xff;
    P0M0=0; P0M1=0x50; P5M0=0; P5M1=0x0c;
    motor_control_init(&control); motor_ir_guard_init(&guard); array_probe_init(&probe);
    memset(conversions,0,sizeof(conversions));
    divider=0; heartbeat=0; adc_timeout=0; adc_register=0; serial_used=0; serial_out[0]=0; ti_register=1;
}
static void released(void) {
    assert((P0M1&0x10)==0x10 && (P0M0&0x10)==0);
    assert((P5M1&0x0c)==0x0c && (P5M0&0x0c)==0);
}
int main(void) {
    unsigned char c,channel,high; unsigned int i;
    for(c=1;c<=6;c++) {
        prepare(); KEY2=0; /* 按键物理为低时，设置P0.4不能改掉P0.2。 */
        handle_command((unsigned char)('A'+c-1)); channel=c>3 ? c-3 : c; high=c>3;
        assert(probe.active==c && KEY2==0);
        assert(strstr(serial_out,"IR006 ADC=0ABC,0123,0FFF\r\nLIVE=1\r\n"));
        assert(conversions[14]==2 && conversions[0]==2 && conversions[1]==2);
        if(channel==1) { assert((P0M0&0x10) && (P0M1&0x10)==0 && ARRAY_TX1==high); }
        else if(channel==2) { assert((P5M0&4) && (P5M1&4)==0 && ARRAY_TX2==high); }
        else { assert((P5M0&8) && (P5M1&8)==0 && ARRAY_TX3==high); }
        for(i=0;i<49;i++) { timer0_isr(); }
        assert(probe.active==c);
        timer0_isr(); assert(probe.active==0); released();
        handle_command('A'); assert(strstr(serial_out,"IR006 REJECT")); released();
    }
    prepare(); control.running=1; handle_command('A'); assert(probe.active==0); released();
    prepare(); handle_command('D'); control.running=1; divider=99; timer0_isr();
    assert(probe.active==0); released(); /* 用户开机的下一扫描取消独立探测。 */
    prepare(); handle_command('F'); control.running=1; guard.actual=1; MOTOR_FI=1;
    handle_command('!'); assert(control.running==0 && guard.actual==0 && MOTOR_FI==0 && MOTOR_BI==0);
    assert(probe.active==0 && probe.cooldown!=0); released();
    prepare(); adc_timeout=1; handle_command('a');
    assert(strstr(serial_out,"ADC=FFFF,FFFF,FFFF") && adc_register==0); released();
    prepare(); handle_command('?'); assert(strstr(serial_out,"IR006 STOP KEYS=111"));
    assert(strstr(serial_out,"ARRAY=SAMPLE"));
    /* 原机械按键3秒启动/停止的实际ISR路径，且从不由未知采样声明光路正常。 */
    for(i=0;i<500;i++) timer0_isr();
    KEY3=0; for(i=0;i<30100;i++) timer0_isr();
    assert(control.running==1 && MOTOR_FI==1 && guard.armed==0);
    KEY3=1; for(i=0;i<500;i++) timer0_isr();
    KEY3=0; for(i=0;i<30100;i++) timer0_isr();
    assert(control.running==0 && MOTOR_FI==0);
    puts("PASS: real array_main probe GPIO/expiry/cancel/ADC discard/timeout/stop/status/3s ISR, simulated registers only");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='probe-host-',dir=root/'build') as folder:
    folder=Path(folder)
    unit=folder/'test.c'; unit.write_text(preamble+native+tests,encoding='utf-8')
    exe=folder/'test.exe'
    subprocess.run(['gcc','-std=c99','-Wall','-Wextra','-Werror','-Wno-unused-function',
                    '-I',str(source.parent),str(unit),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
