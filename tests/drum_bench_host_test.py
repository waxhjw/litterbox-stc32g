"""使用实际 DRUM004 App 解析与控制入口回放两轮换向，不连接主板。"""
from drum_host_test import ROOT, REGISTERS, run_profile


SCENARIOS = r"""
static void feed_clean(unsigned char enabled)
{
    const unsigned char frame[]={0x55,0xAA,0,6,0,5,1,1,0,1,enabled};
    unsigned char sum=0, i;
    for (i=0;i<sizeof frame;i++) { wifi_feed(frame[i]); sum+=frame[i]; }
    wifi_feed(sum);
}

static void simulate_light(unsigned char clear)
{
    carrier.mode=carrier_requested ? CARRIER_SYNC : CARRIER_IDLE;
    beam.age=clear ? 0 : BEAM_CONFIRM;
    beam.seen=clear ? 7 : 0;
    beam.blocked=0;
}

static unsigned char tick(unsigned char light)
{
    simulate_light(light);
    control_drum();
    assert((P2&5)!=5 && drum.stable==DRUM_POSITION_UNKNOWN && drum.completed==0);
    return P2&5;
}

static void press(void)
{
    feed_clean(0);
    feed_clean(1);
}

static void begin(void)
{
    handle_command('g');
    assert(bench.phase==BENCH_ARMED && !bench_release_seen);
    press(); assert(tick(0)==0 && bench.phase==BENCH_WAIT_LIGHT);
}

static void run_until_forward(void)
{
    unsigned char i;
    begin();
    for (i=1;i<DRUM_CLEAR_START;i++) assert(tick(1)==0);
    assert(tick(1)==DRUM_FORWARD);
}

int main(void)
{
    unsigned short i, ticks, length=0;
    unsigned char direction, turn=0, gaps=0, previous=DRUM_STOP;
    const unsigned char expected[]={DRUM_FORWARD,DRUM_REVERSE,DRUM_FORWARD,DRUM_REVERSE};
    P0=0xff; P2=0xfa; P4=0; P1=0x20; link_network=4;
    drum.stable=DRUM_POSITION_UNKNOWN;
    press();
    assert(tick(1)==0 && bench.phase==BENCH_IDLE);
    handle_command('g');
    feed_clean(1);
    assert(tick(1)==0 && bench.phase==BENCH_ARMED); /* 授权前旧请求和同值重发均不启动。 */
    press();
    assert(tick(0)==0 && bench.phase==BENCH_WAIT_LIGHT);
    for (i=0;i<50;i++) assert(tick(0)==0);
    for (ticks=0;ticks<1000 && bench.phase!=BENCH_IDLE;ticks++) {
        direction=tick(1);
        if (direction && previous==DRUM_STOP) {
            assert(turn<4 && direction==expected[turn++]);
            if (turn>1) assert(gaps==BENCH_GAP_TICKS);
            length=0;
            gaps=0;
        }
        if (direction) {
            assert((control_report & DP_STATUS_MASK)==DP_CLEANING);
            length++;
        } else if (previous) {
            assert(length==BENCH_TURN_TICKS);
        }
        if (!direction && turn>0) gaps++;
        previous=direction;
    }
    assert(turn==4 && bench.turns==4 && bench.result==BENCH_DONE && (P2&5)==0);
    press(); assert(tick(1)==0 && bench.phase==BENCH_IDLE);
    puts("PASS: App 请求完成正、反、正、反四段，三次换向有停机间隔，结束后不能重复启动");

    run_until_forward();
    P1=0x60; assert(tick(1)==0 && bench.result==BENCH_BIN_LOST);
    P1=0x20; assert(tick(1)==0 && bench.phase==BENCH_IDLE);
    run_until_forward();
    P4=0x80; assert(tick(1)==0 && bench.result==BENCH_RADAR);
    P4=0; assert(tick(1)==0 && bench.phase==BENCH_IDLE);
    run_until_forward();
    assert(tick(0)==0 && bench.result==BENCH_LIGHT);
    assert(tick(1)==0 && bench.phase==BENCH_IDLE);
    run_until_forward();
    dp_paused=1; assert(tick(1)==0 && bench.result==BENCH_STOPPED);
    dp_paused=0;
    run_until_forward();
    KEY3=0; assert(tick(1)==0 && bench.result==BENCH_STOPPED); KEY3=1;
    run_until_forward();
    handle_command('!'); assert((P2&5)==0 && bench.phase==BENCH_IDLE);
    begin();
    for (i=0;i<BENCH_LIGHT_LIMIT;i++) assert(tick(0)==0);
    assert(bench.result==BENCH_LIGHT && bench.phase==BENCH_IDLE);
    puts("PASS: 霍尔、雷达、红外、暂停、按键和串口停止全部撤销台架输出");
    return 0;
}
"""

if __name__ == "__main__":
    registers = REGISTERS.replace("RI,TI;", "RI;") + """
static unsigned char tx_complete;
static unsigned char *mock_ti(void) { tx_complete=1; return &tx_complete; }
#define TI (*mock_ti())
"""
    run_profile(ROOT / "src/DRUM004", registers, SCENARIOS)
