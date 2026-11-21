/*
 * 三路38kHz载波发生器状态（纯逻辑，由MCU与主机测试共同编译）。
 *
 * 设计要点：
 * 1) 载波由Timer0的13.16us中断直接翻转三个发射脚，不使用硬件PWM。
 *    三路P0.4/P5.2/P5.3分属不同PWM组，硬件配置互不共用；软件翻转可保证三路严格同步。
 * 2) 采用"载波窗口"而非连续发射：每 gate_half 个半周期静默后开一个窗口，
 *    窗口内连续翻转 burst_half 个半周期。FOSC=11.0592MHz时半周期145个时钟→38.13kHz；
 *    每10ms开1ms，平均占空比约5%，发射管不会过热。
 * 3) 本版只保留三路同步发射。轮询模式已删除以压缩代码（评估版2KB限制）。
 */
#ifndef IR_CARRIER_STATE_H
#define IR_CARRIER_STATE_H
#define CARRIER_IDLE 0
#define CARRIER_SYNC 1     /* 三路同相同时发射 */

typedef struct {
    unsigned char mode;          /* CARRIER_IDLE / CARRIER_SYNC */
    unsigned char phase;         /* 当前载波电平，0或1 */
    unsigned char burst_ticks;   /* 窗口内剩余的半周期数 */
    unsigned short gate_ticks;   /* 距离下一个发射窗口的半周期数 */
} IrCarrier;

/* 关断：立即停止发射，避免残留高电平让发射管常亮。 */
static void ir_carrier_stop(volatile IrCarrier *s)
{
    s->mode = CARRIER_IDLE;
}

static void ir_carrier_start(volatile IrCarrier *s)
{
    s->mode = CARRIER_SYNC;
    s->phase = 0;
    s->burst_ticks = 0;
    s->gate_ticks = 1;  /* 下一拍进入首个正常长度的发射窗口。 */
}

/*
 * 每次半周期中断调用一次（13.16us）。
 * 返回：三路发射脚应写入的当前电平（0或1）。
 */
static unsigned char ir_carrier_tick(volatile IrCarrier *s,
                                     unsigned short burst_half,
                                     unsigned short gate_half)
{
    if (s->mode == CARRIER_IDLE) return 0;
    if (s->gate_ticks) {
        s->gate_ticks--;
        if (s->gate_ticks == 0) {
            s->burst_ticks = burst_half;
            s->phase ^= 1;
        } else {
            return 0; /* 静默段输出恒低 */
        }
    } else {
        s->burst_ticks--;
        s->phase ^= 1;
        if (s->burst_ticks == 0) s->gate_ticks = gate_half;
    }
    return s->phase;
}
#endif
