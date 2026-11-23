"""DRUM005 回放实际控制入口、三组保护输入和单路红外时窗。"""
import argparse

from drum_host_test import ROOT, REGISTERS, run_profile


SCENARIOS = r"""
#ifdef EXPECT_ADC_BUDGET
static unsigned char adc_reads, adc_nops, adc_rollover, adc_timeout, adc_channel;

/* 每两条 NOP 对应一次转换，模拟 11 个定时器节拍和低 12 位采样值。 */
static void mock_adc_nop(void)
{
    if (++adc_nops%2) return;
    adc_channel=ADC_CONTR&15;
    adc_reads++;
    carrier.burst_ticks-=11;
    if (adc_rollover && adc_reads==3) {
        ir_beam_close(&beam);
        ir_beam_open(&beam);
        carrier.burst_ticks=BURST_HALF;
    }
    if (adc_timeout) return;
    ADC_RES=0x0B; ADC_RESL=adc_reads;
    ADC_CONTR=(ADC_CONTR&0xBF)|0x20;
}

static void test_adc_window(void)
{
    ir_beam_init(&beam);
    ir_beam_open(&beam);
    IE=0x82;
    carrier.burst_ticks=BEAM_START_TICKS;
    sample_window();
    assert(adc_reads==3 && beam.sampled && IE==0x82);
    ir_beam_close(&beam);
    assert(beam.last[0]==0xB01 && beam.last[2]==0xB03);

    adc_reads=0;
    ir_beam_open(&beam);
    carrier.burst_ticks=BEAM_GUARD_TICKS+33;
    sample_window();
    assert(adc_reads==6 && beam.peak[0]==0xB04);

    adc_reads=0;
    ir_beam_open(&beam);
    carrier.burst_ticks=BEAM_GUARD_TICKS+32;
    sample_window();
    assert(adc_reads==3 && beam.peak[0]==0xB01);

    adc_reads=0; adc_rollover=1;
    ir_beam_open(&beam);
    carrier.burst_ticks=BURST_HALF;
    sample_window();
    assert(adc_reads==3 && beam.in_window && !beam.sampled && beam.peak[0]==0);

    adc_reads=0; adc_rollover=0; adc_timeout=1;
    carrier.burst_ticks=BURST_HALF;
    sample_window();
    assert(adc_reads==1 && !beam.sampled && (ADC_CONTR&0x80));
    assert(adc_read(14)==ADC_INVALID && adc_reads==1);
    ADC_CONTR=0x80; adc_timeout=0; ir_beam_init(&beam);
}
#endif

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

#ifdef EXPECT_ONE_WINDOW_STOP
static void finish_motor_window(unsigned char sampled, unsigned int second_channel)
{
    ir_beam_open(&beam);
    beam.sampled=sampled;
    if (sampled) {
        ir_beam_add(&beam,1000,1000,1000);
        ir_beam_add(&beam,3000,second_channel,3000);
    }
    carrier.burst_ticks=1;
    timer0_isr();
}

static void test_one_window_stop(void)
{
    /* 保持远离下一个 control_drum 调用，单独验收关窗当拍的输出动作。 */
    assert(BEAM_CONFIRM==1 && DRUM_CLEAR_RESUME==502);
    ir_beam_init(&beam);
    carrier.mode=CARRIER_SYNC;
    motor_tick=0;
    P2|=DRUM_FORWARD;
    finish_motor_window(1,3000);
    assert((P2&5)==DRUM_FORWARD && beam.seen==7 && beam.blocked==0);
    finish_motor_window(1,1000);
    assert((P2&5)==0 && beam.blocked==2 && beam.age==0);
    finish_motor_window(1,3000);
    assert((P2&5)==0 && beam.blocked==0);
    P2|=DRUM_REVERSE;
    finish_motor_window(0,0);
    assert((P2&5)==0 && beam.age==1);
    P2|=DRUM_REVERSE;
    finish_motor_window(1,4095);
    assert((P2&5)==0 && beam.blocked==2 && motor_tick==5);
    carrier_requested=0;
    update_carrier();
}
#endif

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

#ifdef EXPECT_PHASE_SCAN
static void test_phase_scan(void)
{
    unsigned char i, cycle, reads;
    const unsigned char channels[]={14,0,1,14,0,1,14,0,1};
    const unsigned char gates[]={60,60,60,42,42,42,24,24,24};
    handle_command('e');
    assert(phase_state==PHASE_RUNNING && inspect_light==INSPECT_PHASE_SCAN);
    handle_command('g');
    app_press();
    control_drum();
    assert(bench.phase==BENCH_IDLE && drum.phase==DRUM_IDLE && (P2&5)==0);
    adc_reads=0;
    for (cycle=0; cycle<PHASE_SAMPLES; cycle++) {
        for (i=0; i<sizeof channels; i++) {
            reads=adc_reads;
            ir_beam_open(&beam);
            carrier.burst_ticks=gates[i]+1U;
            phase_scan_tick();
            assert(adc_reads==reads);
            carrier.burst_ticks=gates[i];
            phase_scan_tick();
            assert(adc_reads==reads+1U && adc_channel==channels[i]);
            assert(phase_cells[i].count==cycle+1U && phase_cells[i].light==cycle+1U);
            assert(phase_cells[i].low==0xB01U+i && phase_cells[i].high==0xB00U+adc_reads);
            if (phase_state==PHASE_RUNNING) {
                carrier.burst_ticks=phase_target;
                phase_scan_tick();
                assert(adc_reads==reads+1U && !beam.sampled);
            }
        }
    }
    assert(phase_state==PHASE_DONE && carrier.mode==CARRIER_IDLE);
    assert(inspect_light==INSPECT_OFF && (P2&5)==0 && !app_start_pending);
    handle_command('y');

    handle_command('e');
    control_clock=(unsigned char)(phase_started+PHASE_LIMIT_TICKS);
    phase_scan_tick();
    assert(phase_state==PHASE_TIMEOUT && carrier.mode==CARRIER_IDLE);
    handle_command('e');
    handle_command('k');
    assert(phase_state==PHASE_CANCELED && carrier.mode==CARRIER_IDLE);
    handle_command('e');
    carrier.burst_ticks=0; carrier.gate_ticks=SINGLE_OPEN_GATE+1U;
    timer0_isr();
    assert(SINGLE_PWM_ENABLE==0);
    handle_command('!');
    assert(phase_state==PHASE_CANCELED && carrier.mode==CARRIER_IDLE && (P2&5)==0);
}
#endif

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

#ifdef EXPECT_SINGLE_TRACE
static void test_single_trace(void)
{
    handle_command('c');
    assert(inspect_light==INSPECT_BOTH && single_windows==0);
    check_waveform(0,0);
    assert(single_windows==1 && single_clear_windows==0);
    assert(single_frame.quiet && single_frame.high==0 && single_frame.first==0xFF);
    check_waveform(0,1);
    assert(single_windows==2 && single_clear_windows==1);
    assert(single_frame.high>=2 && single_frame.edges==2 && single_frame.last==0);
    handle_command('z');
    assert(single_windows==2 && (P2&5)==0);
    handle_command('k');
    assert(carrier.mode==CARRIER_IDLE);
    printf("PASS: 单路红外记录已结算窗口，查询不改变电机输出\n");
}
#endif

#ifdef EXPECT_PERIOD_CHECK
static void test_single_period(unsigned char command, unsigned char divisor)
{
    unsigned short i, frame_tick;
    unsigned char expected;
    handle_command(command);
    assert(carrier.mode==CARRIER_SYNC && single_windows==0);
    handle_command('g');
    assert(bench.phase==BENCH_IDLE);
    for (i=0;i<8U*MOTOR_CONTROL_TICKS;i++) {
        frame_tick=i%MOTOR_CONTROL_TICKS;
        expected=(i/MOTOR_CONTROL_TICKS)%divisor==0 &&
            frame_tick>=MOTOR_CONTROL_TICKS-SINGLE_OPEN_GATE &&
            frame_tick<MOTOR_CONTROL_TICKS-SINGLE_OFF_GATE;
        timer0_isr();
        assert((SINGLE_PWM_ENABLE!=0)==expected && (P2&5)==0);
        expected=frame_tick<BURST_HALF && (frame_tick&1)==0;
        assert(ARRAY_TX1==expected && ARRAY_TX2==expected && ARRAY_TX3==expected);
    }
    assert(single_windows==8U/divisor && single_clear_windows==0 && single_longest_clear==0);
    handle_command('k');
    assert(carrier.mode==CARRIER_IDLE && single_skip==0 && SINGLE_PWM_ENABLE==0);
}
#endif

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
#ifdef EXPECT_ADC_BUDGET
    test_adc_window();
    puts("PASS: ADC 逐轮时序预算，跨窗丢弃，超时不提交且保持 ADC 供电");
#endif
    test_array_block_counter();
    printf("PASS: 三路连续遮挡计数在 %u 次饱和，各路遮挡位置与清除正确\n", BEAM_CONFIRM);
    P0=0xff; P2=0xfa; P4=0; P1=0x20; link_network=4;
    drum.stable=DRUM_POSITION_UNKNOWN;
#ifdef EXPECT_ONE_WINDOW_STOP
    test_one_window_stop();
    puts("PASS: 同窗低值加有效峰值可放行，一窗遮挡、无采样或饱和当拍关闭驱动");
#endif
#ifdef EXPECT_PHASE_SCAN
    test_phase_scan();
    puts("PASS: 三路定相位采样与计数，阻止启动，完成超时或取消均关闭发射");
#endif
#ifdef INSPECT_ARRAY
    check_separate_windows(INSPECT_ARRAY);
    check_separate_windows(INSPECT_BOTH);
    test_light_wait_limit();
    puts("PASS: 三路载波和单路 PWM 独立，旧 5 秒边界可暂停，等待累计 45 秒超时停机");
#endif
#ifdef EXPECT_PAUSE_RESUME
    test_manual_pause_resume();
#endif
#ifdef EXPECT_SINGLE_TRACE
    test_single_trace();
#endif
#ifdef EXPECT_PERIOD_CHECK
    test_single_period('u',2);
    test_single_period('v',4);
    puts("PASS: 20/40ms 只跳过完整的单路窗口，三路发射和电机停止状态不变");
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
    for (i=0;i<DRUM_CLEAR_RESUME*2U/5U;i++) assert(tick(0)==0);
    assert(tick(2)==0); /* 雷达已释放，新的三路遮挡重置计时。 */
    for (i=0;i<DRUM_CLEAR_RESUME*3U/5U;i++) assert(tick(0)==0);
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
    printf("PASS: 三组任一触发暂停，全部连续 %u 个节拍才恢复同方向，正反两轮完整，霍尔脱离取消\n",
           DRUM_CLEAR_RESUME);
    return 0;
}
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("DRUM005", "DRUM006", "DRUM007", "DRUM008", "DRUM009", "DRUM010", "DRUM011", "DRUM012", "DRUM013"), default="DRUM008")
    args = parser.parse_args()
    registers = REGISTERS.replace("RI,TI;", "RI;") + """
static unsigned char tx_complete;
static unsigned char *mock_ti(void) { tx_complete=1; return &tx_complete; }
#define TI (*mock_ti())
#define SINGLE_RX ((P1>>4)&1)
"""
    if args.profile >= "DRUM008":
        registers += "#define EXPECT_PAUSE_RESUME\n"
    if args.profile >= "DRUM009":
        registers += "#define EXPECT_SINGLE_TRACE\n"
    if args.profile >= "DRUM010":
        registers += "#define EXPECT_PERIOD_CHECK\n"
    if args.profile >= "DRUM011":
        registers += "static void mock_adc_nop(void);\n#define _nop_() mock_adc_nop()\n#define EXPECT_ADC_BUDGET\n"
    if args.profile >= "DRUM012":
        registers += "#define EXPECT_PHASE_SCAN\n"
    if args.profile >= "DRUM013":
        registers += "#define EXPECT_ONE_WINDOW_STOP\n"
    run_profile(ROOT / "src" / args.profile, registers, SCENARIOS)
