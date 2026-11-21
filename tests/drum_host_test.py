"""运行滚筒状态机和实际固件控制入口，寄存器及机械反馈由主机模拟。"""
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/DRUM003"

REGISTERS = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define far
#define edata
#define bit unsigned char
#define WIFI_UART_INTERRUPT
typedef union {
    unsigned char byte;
    struct { unsigned char b0:1,b1:1,b2:1,b3:1,b4:1,b5:1,b6:1,b7:1; } bits;
} Port;
static Port p0, p2, p5;
#define P0 p0.byte
#define P2 p2.byte
#define P5 p5.byte
#define KEY1 p2.bits.b6
#define KEY2 p0.bits.b2
#define KEY3 p2.bits.b7
#define MOTOR_BI p2.bits.b0
#define MOTOR_FI p2.bits.b2
#define ARRAY_TX1 p0.bits.b4
#define ARRAY_TX2 p5.bits.b2
#define ARRAY_TX3 p5.bits.b3
static unsigned char P1,P3,P4,P0M0,P0M1,P1M0,P1M1,P2M0,P2M1,P3M0,P3M1,P4M0,P4M1,P5M0,P5M1;
static unsigned char P_SW1,P_SW2,IE,AUXR,TMOD,TL0,TH0,TL1,TH1,SCON,SBUF,WDT_CONTR,RSTCFG;
static unsigned char IE2,IP,S3CON,S3BUF,T4T3M,T3H,T3L,TR0,TF0,TR1,RI,TI;
static unsigned char ADC_CONTR,ADC_RES,ADC_RESL,ADCCFG,xfr[256];
"""

SCENARIOS = r"""
#define READY (DRUM_RADAR_CLEAR|DRUM_PRESENCE_VALID|DRUM_DRIVE_OK|DRUM_BIN_READY)
#define CLEAR (READY|DRUM_LIGHT_CLEAR)

static void advance(DrumCycle *s, const DrumConfig *cfg, unsigned count,
                    unsigned char position, unsigned char inputs)
{
    while (count--) drum_tick(s,cfg,position,inputs);
}

static DrumCycle begin(const DrumConfig *cfg)
{
    DrumCycle s={0};
    advance(&s,cfg,DRUM_STABLE_SAMPLES,cfg->home,READY);
    assert(drum_request(&s,cfg,READY));
    return s;
}

static void test_cycle(DrumConfig cfg)
{
    DrumCycle s=begin(&cfg);
    advance(&s,&cfg,30,cfg.home,READY);
    assert(s.output==DRUM_STOP);
    advance(&s,&cfg,DRUM_CLEAR_START-1,cfg.home,CLEAR);
    assert(s.output==DRUM_STOP);
    advance(&s,&cfg,1,cfg.home,CLEAR);
    assert(s.output==cfg.outbound);
    puts("虚拟原位 P1 → 首次有效通光确认 → 正转");

    advance(&s,&cfg,DRUM_STABLE_SAMPLES,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(!drum_request(&s,&cfg,CLEAR)); /* 正在运行时丢弃重复启动。 */
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,CLEAR|DRUM_PAUSED);
    assert(s.output==DRUM_STOP);
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==cfg.outbound);

    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,READY);
    assert(s.output==DRUM_STOP);
    advance(&s,&cfg,DRUM_CLEAR_RESUME-1,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==DRUM_STOP);
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,CLEAR|DRUM_OCCUPIED);
    assert(s.output==DRUM_STOP && !s.light_ticks);
    advance(&s,&cfg,DRUM_CLEAR_RESUME,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==cfg.outbound);
    puts("遮挡停机，重复遮挡清零计时，稳定通光约 10 秒恢复");

    advance(&s,&cfg,1,cfg.dump,CLEAR);
    assert(s.output==DRUM_STOP && s.phase==DRUM_TO_DUMP);
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==DRUM_STOP); /* 限位抖动也不重新送电。 */
    advance(&s,&cfg,DRUM_STABLE_SAMPLES,cfg.dump,CLEAR);
    assert(s.output==DRUM_STOP && s.phase==DRUM_SETTLE);
    advance(&s,&cfg,cfg.dump_dwell,cfg.dump,CLEAR);
    assert(s.output==DRUM_STOP && s.phase==DRUM_TO_HOME);
    advance(&s,&cfg,1,cfg.dump,CLEAR);
    assert(s.output==cfg.inbound);
    puts("虚拟排泄位 P2 → 停留 → 反转回程");

    advance(&s,&cfg,DRUM_STABLE_SAMPLES,DRUM_BETWEEN_MARKERS,CLEAR);
    advance(&s,&cfg,1,cfg.home,CLEAR);
    assert(s.output==DRUM_STOP && s.completed==0);
    advance(&s,&cfg,DRUM_STABLE_SAMPLES-1,cfg.home,CLEAR);
    assert(s.phase==DRUM_IDLE && s.output==DRUM_STOP && s.completed==1);
    puts("确认回到 P1 → 停机 → 完成计数 +1");
}

static void test_faults(DrumConfig cfg)
{
    DrumCycle s={0};
    advance(&s,&cfg,DRUM_STABLE_SAMPLES,cfg.home,CLEAR);
    assert(!drum_request(&s,&drum_board,CLEAR) && s.fault==DRUM_UNCOMMISSIONED);
    assert(!drum_request(&s,&cfg,READY & ~DRUM_PRESENCE_VALID) && s.fault==DRUM_PRESENCE);

    s=begin(&cfg);
    advance(&s,&cfg,1,cfg.dump,CLEAR);
    assert(s.fault==DRUM_POSITION && s.output==DRUM_STOP);
    assert(!drum_request(&s,&cfg,CLEAR));
    s=begin(&cfg);
    advance(&s,&cfg,DRUM_CLEAR_START,cfg.home,CLEAR);
    advance(&s,&cfg,1,cfg.home,CLEAR & ~DRUM_RADAR_CLEAR);
    assert(s.phase==DRUM_IDLE && s.fault==DRUM_RADAR && s.output==DRUM_STOP);
    advance(&s,&cfg,50,cfg.home,CLEAR);
    assert(s.output==DRUM_STOP);
    assert(drum_request(&s,&cfg,CLEAR)); /* 雷达解除后只接受新的明确操作。 */
    advance(&s,&cfg,1,cfg.home,CLEAR & ~DRUM_DRIVE_OK);
    assert(s.fault==DRUM_DRIVE && s.output==DRUM_STOP);
    assert(!drum_request(&s,&cfg,CLEAR));

    s=begin(&cfg);
    advance(&s,&cfg,cfg.outbound_limit+DRUM_CLEAR_START,cfg.home,CLEAR);
    assert(s.fault==DRUM_TIMEOUT && s.output==DRUM_STOP && s.completed==0);
    s=begin(&cfg);
    advance(&s,&cfg,cfg.cycle_limit,cfg.home,READY|DRUM_PAUSED);
    assert(s.fault==DRUM_TIMEOUT && s.output==DRUM_STOP && s.completed==0);
}

static void test_bin_interlock(DrumConfig cfg)
{
    DrumCycle s={0};
    unsigned char hall, input, base=CLEAR & ~DRUM_BIN_READY;
    for (hall=0;hall<3;hall++) {
        memset(&s,0,sizeof s);
        input=base|drum_board_aux_inputs(hall);
        advance(&s,&cfg,DRUM_STABLE_SAMPLES,cfg.home,input);
        assert(drum_request(&s,&cfg,input));
        advance(&s,&cfg,DRUM_CLEAR_START,cfg.home,input);
        assert(s.output==cfg.outbound);
    }
    memset(&s,0,sizeof s);
    input=base|drum_board_aux_inputs(3);
    advance(&s,&cfg,DRUM_STABLE_SAMPLES,cfg.home,input);
    assert(!drum_request(&s,&cfg,input));
    assert(s.fault==DRUM_BIN && s.output==DRUM_STOP);
    assert(drum_request(&s,&cfg,CLEAR));
    advance(&s,&cfg,DRUM_CLEAR_START,cfg.home,CLEAR);
    advance(&s,&cfg,DRUM_STABLE_SAMPLES,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==cfg.outbound);
    /* 两路切换期间只要仍有一路感应就继续，两路均未感应的下一拍停机。 */
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,base|drum_board_aux_inputs(1));
    assert(s.output==cfg.outbound);
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,base|drum_board_aux_inputs(2));
    assert(s.output==cfg.outbound);
    advance(&s,&cfg,1,DRUM_BETWEEN_MARKERS,input);
    assert(s.phase==DRUM_IDLE && s.output==DRUM_STOP && s.fault==DRUM_BIN);
    advance(&s,&cfg,10,DRUM_BETWEEN_MARKERS,CLEAR);
    assert(s.output==DRUM_STOP && s.completed==0);
    assert(!drum_request(&s,&cfg,CLEAR) && s.fault==DRUM_POSITION);

    s=begin(&cfg);
    advance(&s,&cfg,1,DRUM_POSITION_UNKNOWN,CLEAR);
    assert(s.output==DRUM_STOP && s.fault==DRUM_POSITION);
    puts("PASS: 集便仓不到位拒绝启动，取出即撤销驱动，装回不自启，未知滚筒位置独立停机");
}

static void test_auto(void)
{
    DrumAuto a={0};
    unsigned short delay=DRUM_AUTO_DELAY_TICKS;
    unsigned short i;
    assert(!drum_auto_tick(&a,CLEAR,delay));
    assert(!drum_auto_tick(&a,READY|DRUM_OCCUPIED,delay));
    for (i=0;i<delay-1;i++) assert(!drum_auto_tick(&a,CLEAR,delay));
    assert(!drum_auto_tick(&a,CLEAR|DRUM_OCCUPIED,delay));
    for (i=0;i<delay-1;i++) assert(!drum_auto_tick(&a,CLEAR,delay));
    assert(drum_auto_tick(&a,CLEAR,delay));
    assert(!drum_auto_tick(&a,CLEAR,delay));
    assert(!drum_auto_tick(&a,READY|DRUM_OCCUPIED,delay));
    assert(!drum_auto_tick(&a,DRUM_RADAR_CLEAR,delay));
    assert(!drum_auto_tick(&a,CLEAR,delay) && !a.seen_occupancy);
    assert(!drum_auto_tick(&a,READY|DRUM_OCCUPIED,delay));
    assert(!drum_auto_tick(&a,CLEAR & ~DRUM_BIN_READY,delay) && !a.seen_occupancy);
}

static void test_other_programs(void)
{
    unsigned char job;
    for (job=DRUM_JOB_SMOOTH;job<=DRUM_JOB_EMPTY;job++) {
        DrumConfig cfg=*drum_job_config(job);
        DrumCycle state;
        cfg.verified=1;
        state=begin(&cfg);
        advance(&state,&cfg,DRUM_CLEAR_START,cfg.home,CLEAR);
        assert(state.output==cfg.outbound);
        advance(&state,&cfg,DRUM_STABLE_SAMPLES,DRUM_BETWEEN_MARKERS,CLEAR);
        advance(&state,&cfg,DRUM_STABLE_SAMPLES,cfg.dump,CLEAR);
        assert(state.phase==DRUM_SETTLE);
        advance(&state,&cfg,cfg.dump_dwell,cfg.dump,CLEAR);
        advance(&state,&cfg,1,cfg.dump,CLEAR);
        assert(state.output==cfg.inbound);
        advance(&state,&cfg,DRUM_STABLE_SAMPLES,DRUM_BETWEEN_MARKERS,CLEAR);
        advance(&state,&cfg,DRUM_STABLE_SAMPLES,cfg.home,CLEAR);
        assert(state.phase==DRUM_IDLE && state.completed==1);
    }
    puts("PASS: 平砂和倾空使用各自的虚拟限位、方向和停留时间");
}

static void tick_mcu(unsigned count)
{
    while (count--) {
        motor_tick=MOTOR_CONTROL_TICKS-1;
        timer0_isr();
        assert((P2&5)==0); /* 交付镜像的板级配置未验收，所有命令保持两路低。 */
    }
}

static void feed_frame(unsigned char cmd, const unsigned char *data, unsigned char length)
{
    unsigned char sum=(unsigned char)(0xff+cmd+length), i;
    wifi_feed(0x55); wifi_feed(0xaa); wifi_feed(0); wifi_feed(cmd);
    wifi_feed(0); wifi_feed(length);
    for (i=0;i<length;i++) { wifi_feed(data[i]); sum+=data[i]; }
    wifi_feed(sum);
}

static void test_mcu(void)
{
    unsigned char network[]={4};
    unsigned char start[]={1,1,0,1,1}, pause[]={5,1,0,1,1}, automatic_dp[]={12,1,0,1,1};
    unsigned char invalid[]={1,1,0,1,0,5,1,0,2,1};
    MotorControl keys={0};
    unsigned i;
    assert(!motor_control_tick(&keys,KEY_CLEAN));
    assert(!motor_control_tick(&keys,KEY_CLEAN)); /* 上电按住不发命令。 */
    motor_control_tick(&keys,0); assert(!motor_control_tick(&keys,0));
    motor_control_tick(&keys,KEY_CLEAN); motor_control_tick(&keys,KEY_CLEAN);
    motor_control_tick(&keys,0); assert(motor_control_tick(&keys,0)==KEY_CLEAN);
    motor_control_tick(&keys,1);
    for (i=1;i<300;i++) assert(!motor_control_tick(&keys,1));
    assert(motor_control_tick(&keys,1)==(KEY_LONG|1));
    motor_control_tick(&keys,0); assert(!motor_control_tick(&keys,0));

    P0=0xff; P2=0xfa; P4=0;
    radar_idle=1;
    for (i=0;i<4;i++) {
        P1=(unsigned char)(i<<5); tick_mcu(8);
        assert(bin_ready==(i<3));
        assert(drum.stable==DRUM_POSITION_UNKNOWN); /* H 只影响集便仓。 */
    }
    puts("PASS: 集便仓霍尔 H0/H1/H2 在位，H3 未到位");
    feed_frame(3,network,sizeof network);
    feed_frame(6,start,sizeof start);
    assert(app_start_pending && dp_manual_level==1);
    tick_mcu(2);
    assert(drum.fault==DRUM_UNCOMMISSIONED && !app_start_pending);
    feed_frame(6,start,sizeof start);
    assert(!app_start_pending);
    feed_frame(6,invalid,sizeof invalid);
    assert(dp_invalid==1 && dp_manual_level==1 && dp_paused==0);
    feed_frame(6,pause,sizeof pause); tick_mcu(1);
    assert(control_report & DP_PAUSE_APPLIED);
    pause[4]=0; feed_frame(6,pause,sizeof pause); tick_mcu(1);
    assert(!(control_report & DP_PAUSE_APPLIED));
    feed_frame(6,automatic_dp,sizeof automatic_dp); tick_mcu(1);
    assert(dp_auto_seen && !dp_auto_level && !(control_report & DP_AUTO_ACTIVE));
    tx_busy=1; tx_tail=tx_head=0; dp_reports=0;
    wifi_service();
    assert(dp_reports==1 && tx_head==41);
    assert(wifi_tx[6]==1 && wifi_tx[11]==5 && wifi_tx[23]==22 && wifi_tx[35]==12);
    assert(wifi_tx[39]==0); /* 真实 DP12 回报关闭。 */
    KEY3=0; tick_mcu(10); KEY3=1; tick_mcu(2);
    assert(drum.fault==DRUM_UNCOMMISSIONED && drum.phase==DRUM_IDLE);
    puts("PASS: 真实控制节拍、按键、涂鸦报文、交付板级锁定");
}

int main(void)
{
    DrumConfig demo=drum_board;
    demo.verified=1; /* 只供主机仿真。目标镜像配置保持未验收。 */
    test_cycle(demo);
    test_faults(demo);
    test_bin_interlock(demo);
    test_auto();
    test_other_programs();
    test_mcu();
    puts("PASS: 滚筒行程、遮挡恢复、位置故障、驱动故障、停机和离开倒计时");
    return 0;
}
"""


def run_profile(directory, registers, scenarios):
    source = (directory / "array_main.c").read_text(encoding="utf-8")
    source = re.sub(r"sfr P0=.*?(?=#define XREG)", "", source, flags=re.S)
    source = re.sub(r"#define XREG\(addr\).*", "#define XREG(addr) xfr[(addr)&255]", source)
    source = source.replace(" interrupt 1", "").replace("void main(void)", "void firmware_main(void)")
    with tempfile.TemporaryDirectory(prefix="drum-host-", dir=ROOT / "build") as temp:
        unit = Path(temp) / "drum_host.c"
        binary = Path(temp) / "drum_host.exe"
        unit.write_text(registers + source + scenarios, encoding="utf-8")
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(directory), str(unit), "-o", str(binary)],
            check=True,
        )
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    run_profile(SOURCE, REGISTERS, SCENARIOS)
