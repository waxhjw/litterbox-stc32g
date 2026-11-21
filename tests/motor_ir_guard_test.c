#include <assert.h>
#include <stdio.h>
#include "../diagnostics/shared/motor_ir_guard.h"
static MotorIrGuard g;
static void feed(unsigned char request, unsigned char sensor, unsigned int ticks)
{
    while (ticks--) motor_ir_guard_tick(&g, request, sensor);
}
int main(void)
{
    motor_ir_guard_init(&g);
    feed(0, IR_CLEAR, 1); assert(g.actual==0); /* 上电无人也不自行启动。 */
    feed(1, IR_CLEAR, 1); assert(g.actual==1); /* 用户请求运行。 */
    feed(1, IR_TRIGGER, 1); assert(g.actual==0); /* 下次10ms控制立即禁止输出。 */
    feed(1, IR_TRIGGER, 3000); assert(g.actual==0); /* 一直触发绝不恢复。 */
    feed(1, IR_CLEAR, 999); assert(g.actual==0); /* 9.99秒仍保持停止。 */
    feed(1, IR_CLEAR, 1); assert(g.actual==1); /* 满10秒恢复。 */
    feed(1, IR_TRIGGER, 1); feed(1, IR_CLEAR, 900);
    feed(1, IR_TRIGGER, 1); feed(1, IR_CLEAR, 999); assert(g.actual==0);
    feed(1, IR_CLEAR, 1); assert(g.actual==1); /* 9秒时再触发，从零重计。 */
    feed(1, IR_TRIGGER, 1); feed(0, IR_CLEAR, 1500); assert(g.actual==0);
    feed(1, IR_CLEAR, 1); assert(g.actual==1); /* 用户再次明确请求。 */
    feed(1, IR_UNKNOWN, 2000); assert(g.actual==0);
    feed(1, IR_CLEAR, 999); assert(g.actual==0);
    feed(1, IR_CLEAR, 1); assert(g.actual==1); /* 未知期间不计入无触发时间。 */
    puts("PASS: immediate output inhibit, persistent trigger, 10s resume, retrigger, manual stop, unknown");
    return 0;
}
