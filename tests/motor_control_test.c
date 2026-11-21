/* 回放真实固件的控制逻辑，验证启停边界；不替代硬件实测。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/MOTOR003/motor_control.h"
static MotorControl c;
static void feed(unsigned char pressed, unsigned int ticks)
{
    while (ticks--) motor_control_tick(&c, pressed);
}
int main(void)
{
    motor_control_init(&c);
    feed(1, 1000); assert(c.running == 0); /* 上电按住10秒不启动。 */
    feed(0, 5); feed(1, 299); assert(c.running == 0); /* 不足3秒。 */
    feed(0, 5); feed(1, 301); assert(c.running == 1); /* 长按启动。 */
    feed(1, 10000); assert(c.running == 1); /* 持续按住不重复切换。 */
    feed(0, 5); feed(1, 301); assert(c.running == 0); /* 长按停止。 */
    feed(0, 5); feed(1, 200); feed(0, 5);
    feed(1, 200); assert(c.running == 0); /* 短按不能累加。 */
    feed(0, 5); feed(1, 301); assert(c.running == 1);
    motor_control_stop(&c); feed(1, 1000); assert(c.running == 0);
    feed(0, 5); feed(1, 301); assert(c.running == 1); /* 停止后先松手。 */
    motor_control_init(&c); feed(0, 5);
    feed(1, 1); feed(0, 1); feed(1, 1); feed(0, 5);
    assert(c.running == 0); /* 抖动不能启动。 */
    feed(2, 301); assert(c.running == 1); /* 第二个键也可启动。 */
    feed(0, 5); feed(4, 301); assert(c.running == 0); /* 第三个键停止。 */
    feed(0, 5); feed(1, 200); feed(2, 200); assert(c.running == 0);
    feed(0, 5); feed(3, 1000); assert(c.running == 0); /* 多键组合不启动。 */
    puts("PASS: boot-held, short press, 3s start/stop, no-repeat, release, stop, bounce");
    return 0;
}
