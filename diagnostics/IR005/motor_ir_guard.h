/*
 * 红外联动的纯控制逻辑：每10ms输入一次“已确认有效”的传感器状态。
 * IR004电机测试策略：本次启动先允许运行，首次有效通光后才建立遮挡保护。
 * 未连接/从未得到有效通光时不阻止测试运行；不能因此声称光路安全。
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
    unsigned char armed;
} MotorIrGuard;

static void motor_ir_guard_init(volatile MotorIrGuard *s)
{
    s->clear_ticks_left=0;
    s->actual=0;
    s->armed=0;
}

static void motor_ir_guard_tick(volatile MotorIrGuard *s, unsigned char requested,
                                unsigned char sensor)
{
    s->actual=requested;
    if (requested==0) {
        /* 长按关机取消恢复，并清除本轮识别状态；下一次开机重新识别。 */
        s->armed=0;
        s->clear_ticks_left=0;
    } else if (s->armed==0) {
        /* 用户要求未插红外也能测试电机；首次收到有效脉冲后才开始保护。 */
        if (sensor==IR_CLEAR) s->armed=1;
    } else {
        /* 已建立有效光路后，遮挡/信号丢失都暂停，持续异常不恢复。 */
        if (sensor!=IR_CLEAR) s->clear_ticks_left=IR_RESUME_TICKS;
        else if (s->clear_ticks_left!=0) s->clear_ticks_left--;
        /* actual已由有效用户请求置1；还有等待时间时才改为0。 */
        if (s->clear_ticks_left!=0) s->actual=0;
    }
    /* 手动关闭requested后不会恢复；再次长按才是新的运行请求。 */
}
#endif
