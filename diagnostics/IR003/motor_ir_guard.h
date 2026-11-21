/*
 * 红外联动的纯控制逻辑：每10ms输入一次“已确认有效”的传感器状态。
 * 原始电平与IR_CLEAR/IR_TRIGGER的映射须经本板实测；未知不能当作无人。
 * requested是原有长按逻辑的用户运行意图，actual才是允许下发的电机输出。
 */
#ifndef MOTOR_IR_GUARD_H
#define MOTOR_IR_GUARD_H
#define IR_UNKNOWN 0
#define IR_CLEAR 1
#define IR_TRIGGER 2
#define IR_RESUME_TICKS 1000U
typedef struct {
    unsigned short clear_ticks_left;
    unsigned char actual;
    unsigned char initialized;
} MotorIrGuard;

static void motor_ir_guard_init(volatile MotorIrGuard *s)
{
    s->clear_ticks_left=IR_RESUME_TICKS;
    s->actual=0;
    s->initialized=0;
}

static void motor_ir_guard_tick(volatile MotorIrGuard *s, unsigned char requested,
                                unsigned char sensor)
{
    if (sensor!=IR_CLEAR) {
        /* 触发或未知都停止，并重新计时；未知不是“10秒无人”的证据。 */
        s->actual=0;
        s->clear_ticks_left=IR_RESUME_TICKS;
        s->initialized=1;
        return;
    }
    if (s->initialized==0) {
        /* 首次有效清空状态不自动启动，仍由用户长按的requested决定。 */
        s->initialized=1;
        s->clear_ticks_left=0;
    }
    if (s->clear_ticks_left!=0) s->clear_ticks_left--;
    /* 手动关闭requested后不会恢复；再次长按才是新的运行请求。 */
    s->actual=(requested!=0 && s->clear_ticks_left==0) ? 1 : 0;
}
#endif
