/*
 * 红外联动的纯控制逻辑：每10ms输入一次“已确认有效”的传感器状态。
 * 正常模式等待首次有效通光。遮挡或已通光后的信号丢失重置恢复等待。
 * requested是原有长按逻辑的用户运行意图，actual才是允许下发的电机输出。
 */
#ifndef MOTOR_IR_GUARD_H
#define MOTOR_IR_GUARD_H
#define IR_RESUME_TICKS 1005U
typedef struct {
    unsigned short clear_ticks_left;
    unsigned char actual;
} MotorIrGuard;

static void motor_ir_guard_init(volatile MotorIrGuard *s)
{
    s->clear_ticks_left=0;
    s->actual=0;
}

static void motor_ir_guard_tick(volatile MotorIrGuard *s, unsigned char requested,
                                unsigned char clear)
{
    s->actual=0;
    if (requested==0) {
        s->clear_ticks_left=0;
    } else if (clear) {
        if (s->clear_ticks_left) s->clear_ticks_left--;
        s->actual=s->clear_ticks_left==0;
    } else {
        /* 上电初次等待光路、遮挡和采样失效都重新计满恢复时间。 */
        s->clear_ticks_left=IR_RESUME_TICKS;
    }
}
#endif
