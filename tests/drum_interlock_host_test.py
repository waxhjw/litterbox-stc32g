"""DRUM005 回放实际控制入口、三组保护输入和单路红外时窗。"""
import argparse

from drum_host_test import ROOT, REGISTERS, run_profile


SCENARIOS = r"""
static void test_array_block_counter(void)
{
    IrBeam state;
    unsigned char i, channel;
    for (channel=0;channel<3;channel++) {
        ir_beam_init(&state);
        ir_beam_open(&state);
        state.sampled=1;
        ir_beam_add(&state,3000,3000,3000);
        ir_beam_close(&state);
        assert(state.seen==7 && state.blocked==0);
        for (i=1;i<=BEAM_CONFIRM+3;i++) {
            ir_beam_open(&state);
            state.sampled=1;
            ir_beam_add(&state,channel==0 ? 1000 : 3000,
                channel==1 ? 1000 : 3000,channel==2 ? 1000 : 3000);
            ir_beam_close(&state);
            assert(state.miss[channel]==(i < BEAM_CONFIRM ? i : BEAM_CONFIRM));
            assert(state.blocked==(i < BEAM_CONFIRM ? 0 : 1U<<channel));
        }
        ir_beam_open(&state);
        state.sampled=1;
        ir_beam_add(&state,3000,3000,3000);
        ir_beam_close(&state);
        assert(state.miss[channel]==0 && state.blocked==0);
    }
}

static void app_press(void)
{
    unsigned char frame[]={0x55,0xAA,0,6,0,5,1,1,0,1,0};
    unsigned char sum, i, value;
    for (value=0;value<2;value++) {
        frame[10]=value;
        sum=0;
        for (i=0;i<sizeof frame;i++) { wifi_feed(frame[i]); sum+=frame[i]; }
        wifi_feed(sum);
    }
}

static unsigned char tick(unsigned char blocked)
{
    P4=(blocked&1) ? 0x80 : 0;
    beam.seen=7;
    beam.age=0;
    beam.blocked=(blocked&2) ? 1 : 0;
    single_ir.state=(blocked&4) ? SINGLE_INVALID : SINGLE_CLEAR;
    carrier.mode=carrier_requested ? CARRIER_SYNC : CARRIER_IDLE;
    control_drum();
    assert((P2&5)!=5 && drum.stable==DRUM_POSITION_UNKNOWN && drum.completed==0);
    return P2&5;
}

static void begin(void)
{
    handle_command('g');
    assert(bench.phase==BENCH_ARMED);
    app_press();
    assert(tick(4)==0 && bench.phase==BENCH_WAIT_LIGHT);
}

static void check_waveform(unsigned char initially_high, unsigned char pattern)
{
    unsigned short i;
    carrier.burst_ticks=0;
    beam.in_window=0;
    for (i=0;i<=SINGLE_OPEN_GATE;i++) {
        unsigned char high=initially_high;
        if (pattern==1 && i>=16 && i<64) high=1;
        if (pattern==2 && i>=264 && i<330) high=1;
        if (high) P1|=0x10; else P1&=0xEF;
        carrier.gate_ticks=(unsigned short)(SINGLE_OPEN_GATE+1-i);
        timer0_isr();
        if (i==0) assert(SINGLE_PWM_ENABLE==0x80);
        if (i==SINGLE_OPEN_GATE-SINGLE_OFF_GATE) assert(SINGLE_PWM_ENABLE==0);
    }
}

#ifdef INSPECT_ARRAY
static void check_separate_windows(unsigned char inspect_mode)
{
    unsigned short tick_index, frame_tick, array_high=0, single_on=0;
    unsigned char expect_array, expect_single;

    inspect_light=inspect_mode;
    carrier_requested=1;
    update_carrier();
    /* 连续两帧逐拍检查，避免关窗多一个脉冲或隔帧起始相位反转。 */
    for (tick_index=0;tick_index<2U*MOTOR_CONTROL_TICKS;tick_index++) {
        frame_tick=tick_index%MOTOR_CONTROL_TICKS;
        expect_array=frame_tick<BURST_HALF && (frame_tick&1)==0;
        expect_single=inspect_mode==INSPECT_BOTH &&
            frame_tick>=BURST_HALF+GATE_HALF-SINGLE_OPEN_GATE &&
            frame_tick<BURST_HALF+GATE_HALF-SINGLE_OFF_GATE;
        timer0_isr();
        assert(ARRAY_TX1==expect_array && ARRAY_TX2==expect_array && ARRAY_TX3==expect_array);
        assert((SINGLE_PWM_ENABLE!=0)==expect_single);
        assert(beam.in_window==(frame_tick<BURST_HALF));
        if (expect_array) array_high++;
        if (expect_single) single_on++;
    }
    assert(array_high==BURST_HALF);
    assert(single_on==(inspect_mode==INSPECT_BOTH ? 2U*BURST_HALF : 0));
    assert((P2&5)==0);
    inspect_light=INSPECT_OFF;
    carrier_requested=0;
    update_carrier();
    assert(SINGLE_PWM_ENABLE==0 && single_ir.state==SINGLE_UNKNOWN);
}

static void test_light_wait_limit(void)
{
    unsigned short i;
    begin();
    /* 遮挡持续超过旧版 5 秒，输出依旧为零，台架还接受暂停。 */
    for (i=0;i<500;i++) assert(tick(4)==0);
    assert(bench.phase==BENCH_WAIT_LIGHT && (control_report&DP_STATUS_MASK)==DP_WAITING);
    dp_paused=1;
#ifdef EXPECT_PAUSE_RESUME
    i=bench.left;
    assert(tick(4)==0 && bench.phase==BENCH_WAIT_LIGHT && bench.left==i);
    assert((control_report&DP_PAUSE_APPLIED)!=0);
    handle_command('!');
#else
    assert(tick(4)==0 && bench.result==BENCH_STOPPED);
#endif
    dp_paused=0;

    begin();
    for (i=1;i<BENCH_LIGHT_LIMIT;i++) assert(tick(4)==0);
    assert(bench.phase==BENCH_WAIT_LIGHT);
    assert(tick(4)==0 && bench.result==BENCH_START_BLOCKED);
}
#endif

#ifdef EXPECT_PAUSE_RESUME
static void app_pause(unsigned char value)
{
    unsigned char frame[]={0x55,0xAA,0,6,0,5,5,1,0,1,0};
    unsigned char sum=0, i;
    frame[10]=value;
    for (i=0;i<sizeof frame;i++) { wifi_feed(frame[i]); sum+=frame[i]; }
    wifi_feed(sum);
}

static void test_manual_pause_resume(void)
{
    unsigned short i, remaining;
    begin();
    for (i=1;i<DRUM_CLEAR_START;i++) assert(tick(0)==0);
    assert(tick(0)==DRUM_FORWARD);
    remaining=bench.left;
    app_pause(1);
    for (i=0;i<100;i++) assert(tick(0)==0);
    assert(bench.phase==BENCH_TURN && bench.left==remaining && bench.turns==0);
    assert(dp_last_id==5 && (control_report&DP_PAUSE_APPLIED)!=0);
    assert(tick(1)==0); /* 暂停期间雷达触发。 */
    app_pause(0);
    assert(tick(4)==0); /* 已继续但单路尚未放行。 */
    for (i=1;i<DRUM_CLEAR_RESUME;i++) assert(tick(0)==0);
    assert(tick(0)==DRUM_FORWARD && bench.left==remaining-1);
    assert((control_report&DP_PAUSE_APPLIED)==0);
    app_pause(1);
    assert(tick(0)==0);
    P1=0x60;
    assert(tick(0)==0 && bench.phase==BENCH_IDLE && bench.result==BENCH_BIN_LOST);
    P1=0x20;
    app_pause(0);
    assert(tick(0)==0 && bench.phase==BENCH_IDLE);
    puts("PASS: DP5 暂停保留进度，继续受三组联锁控制，集便仓脱离仍取消任务");
}
#endif

static void test_product_resume(void)
{
    DrumConfig cfg=drum_board;
    DrumCycle state={0};
    unsigned short i, remaining;
    const unsigned char input=DRUM_ENV_CLEAR|DRUM_BIN_READY|DRUM_PRESENCE_VALID|DRUM_DRIVE_OK;
    cfg.verified=1;
    for (i=0;i<DRUM_STABLE_SAMPLES;i++) drum_tick(&state,&cfg,cfg.home,input);
    assert(drum_request(&state,&cfg,input));
    for (i=0;i<DRUM_CLEAR_START;i++) drum_tick(&state,&cfg,cfg.home,input);
    assert(state.output==DRUM_FORWARD);
    remaining=state.cycle_left;
    for (i=0;i<cfg.cycle_limit;i++) {
        drum_tick(&state,&cfg,DRUM_BETWEEN_MARKERS,input & ~DRUM_RADAR_CLEAR);
        assert(state.output==0 && state.phase==DRUM_TO_DUMP);
    }
    assert(state.cycle_left==remaining);
    for (i=0;i<DRUM_CLEAR_RESUME-1;i++) {
        drum_tick(&state,&cfg,DRUM_BETWEEN_MARKERS,input);
        assert(state.output==0);
    }
    drum_tick(&state,&cfg,DRUM_BETWEEN_MARKERS,input);
    assert(state.output==DRUM_FORWARD);
}

int main(void)
{
    unsigned short i, remaining;
    unsigned char result, direction, seen=0, previous=0;
    const unsigned char order[]={DRUM_FORWARD,DRUM_REVERSE,DRUM_FORWARD,DRUM_REVERSE};
    test_array_block_counter();
    puts("PASS: 三路连续遮挡计数在四次饱和，各路遮挡位置与清除正确");
    P0=0xff; P2=0xfa; P4=0; P1=0x20; link_network=4;
    drum.stable=DRUM_POSITION_UNKNOWN;
#ifdef INSPECT_ARRAY
    check_separate_windows(INSPECT_ARRAY);
    check_separate_windows(INSPECT_BOTH);
    test_light_wait_limit();
    puts("PASS: 三路载波和单路 PWM 独立，旧 5 秒边界可暂停，等待累计 45 秒超时停机");
#endif
#ifdef EXPECT_PAUSE_RESUME
    test_manual_pause_resume();
#endif
    carrier.mode=CARRIER_SYNC;
    check_waveform(0,0);
    assert(single_ir.state==SINGLE_INVALID);
    check_waveform(1,0);
    assert(single_ir.state==SINGLE_INVALID);
    check_waveform(0,2);
    assert(single_ir.state==SINGLE_INVALID);
    check_waveform(0,1);
    assert(single_ir.state==SINGLE_CLEAR);
    puts("PASS: 单路独立发射时窗，高脉冲判据，固定高低和迟到脉冲拒绝放行");

    begin();
    for (i=0;i<50;i++) assert(tick(4)==0);
    for (i=1;i<DRUM_CLEAR_START;i++) assert(tick(0)==0);
    assert(tick(0)==DRUM_FORWARD);
    remaining=bench.left;
    for (i=0;i<2000;i++) assert(tick(1)==0);
    assert(bench.left==remaining && bench.turns==0);
    for (i=0;i<400;i++) assert(tick(0)==0);
    assert(tick(2)==0); /* 雷达已释放，新的三路遮挡重置计时。 */
    for (i=0;i<600;i++) assert(tick(0)==0);
    assert(tick(4)==0); /* 单路遮挡继续重置，不能按各路分开累计。 */
    for (i=0;i<DRUM_CLEAR_RESUME-1;i++) assert(tick(0)==0);
    assert(bench.left==remaining && bench.turns==0);
    direction=tick(0);
    assert(direction==DRUM_FORWARD && bench.left==remaining-1);
    while (bench.phase!=BENCH_IDLE) {
        if (direction && previous==0) {
            assert(seen<4 && direction==order[seen++]);
        }
        previous=direction;
        direction=tick(0);
    }
    assert(seen==4 && bench.turns==4 && bench.result==BENCH_DONE && (P2&5)==0);
    app_press(); assert(tick(0)==0 && bench.phase==BENCH_IDLE);
    begin();
    for (i=0;i<DRUM_CLEAR_START;i++) result=tick(0);
    assert(result==DRUM_FORWARD);
    assert(tick(2)==0);
    P1=0x60; assert(tick(0)==0 && bench.result==BENCH_BIN_LOST);
    P1=0x20; assert(tick(0)==0 && bench.phase==BENCH_IDLE);
    test_product_resume();
    puts("PASS: 三组任一触发暂停，全部连续10秒才恢复同方向，正反两轮完整，霍尔脱离取消");
    return 0;
}
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("DRUM005", "DRUM006", "DRUM007", "DRUM008"), default="DRUM008")
    args = parser.parse_args()
    registers = REGISTERS.replace("RI,TI;", "RI;") + """
static unsigned char tx_complete;
static unsigned char *mock_ti(void) { tx_complete=1; return &tx_complete; }
#define TI (*mock_ti())
#define SINGLE_RX ((P1>>4)&1)
"""
    if args.profile == "DRUM008":
        registers += "#define EXPECT_PAUSE_RESUME\n"
    run_profile(ROOT / "src" / args.profile, registers, SCENARIOS)
