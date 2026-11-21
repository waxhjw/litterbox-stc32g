/* 只用于固定、空载的台架电机。定时段代表虚拟一圈，不能作为实体位置反馈。 */
#ifndef DRUM_BENCH_H
#define DRUM_BENCH_H
#include "drum_cycle.h"

#define BENCH_ARM_TICKS 9000U
#define BENCH_LIGHT_LIMIT 500U
#define BENCH_TURN_TICKS 100U
#define BENCH_GAP_TICKS 30U
#define BENCH_TURNS 4U

enum BenchPhase { BENCH_IDLE, BENCH_ARMED, BENCH_WAIT_LIGHT, BENCH_TURN, BENCH_GAP };
enum BenchResult { BENCH_NONE, BENCH_DONE, BENCH_BIN_LOST, BENCH_RADAR,
                   BENCH_LIGHT, BENCH_STOPPED, BENCH_EXPIRED };
typedef struct {
    unsigned short left;
    unsigned char phase, clear_ticks, turns, result;
} DrumBench;

static void bench_arm(volatile DrumBench *s)
{
    s->left=BENCH_ARM_TICKS;
    s->clear_ticks=0;
    s->turns=0;
    s->result=BENCH_NONE;
    s->phase=BENCH_ARMED;
}

static unsigned char bench_stop(volatile DrumBench *s, unsigned char result)
{
    s->result=result;
    s->phase=BENCH_IDLE;
    return DRUM_STOP;
}

static unsigned char bench_tick(volatile DrumBench *s, unsigned char input,
                                unsigned char online, unsigned char request)
{
    if (s->phase==BENCH_IDLE) return DRUM_STOP;
    if (online==0 || (input & DRUM_PAUSED)) return bench_stop(s,BENCH_STOPPED);
    if ((input & DRUM_BIN_READY)==0) return bench_stop(s,BENCH_BIN_LOST);
    if ((input & DRUM_RADAR_CLEAR)==0) return bench_stop(s,BENCH_RADAR);

    if (s->phase==BENCH_ARMED) {
        if (request) {
            s->phase=BENCH_WAIT_LIGHT;
            s->left=BENCH_LIGHT_LIMIT;
        } else if (--s->left==0) return bench_stop(s,BENCH_EXPIRED);
        return DRUM_STOP;
    }
    if (s->phase==BENCH_WAIT_LIGHT) {
        if (--s->left==0) return bench_stop(s,BENCH_LIGHT);
        if ((input & DRUM_LIGHT_CLEAR)==0) {
            s->clear_ticks=0;
            return DRUM_STOP;
        }
        if (++s->clear_ticks<DRUM_CLEAR_START) return DRUM_STOP;
        s->phase=BENCH_TURN;
        s->left=BENCH_TURN_TICKS;
    } else {
        /* 一旦已经开始动作，光路丢失立即取消整次试转。 */
        if ((input & DRUM_LIGHT_CLEAR)==0) return bench_stop(s,BENCH_LIGHT);
        if (--s->left==0) {
            if (s->phase==BENCH_TURN) {
                if (++s->turns==BENCH_TURNS) return bench_stop(s,BENCH_DONE);
                s->phase=BENCH_GAP;
                s->left=BENCH_GAP_TICKS;
            } else {
                s->phase=BENCH_TURN;
                s->left=BENCH_TURN_TICKS;
            }
        }
    }
    if (s->phase==BENCH_GAP) return DRUM_STOP;
    return (s->turns & 1) ? DRUM_REVERSE : DRUM_FORWARD;
}
#endif
