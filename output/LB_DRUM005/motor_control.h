/* 每约 10ms 扫描一次，短按和长按只产生一次事件。 */
#ifndef MOTOR_CONTROL_H
#define MOTOR_CONTROL_H
#define KEY_CLEAN 4U
#define KEY_LONG 0x10U
typedef struct {
    unsigned char candidate, debounce, armed, fired, held_key;
    unsigned short hold_ticks;
} MotorControl;
static void motor_control_stop(volatile MotorControl *s)
{
    s->armed = 0;
    s->fired = 1;
    s->hold_ticks = 0;
    s->held_key = 0;
}
static unsigned char motor_control_tick(volatile MotorControl *s, unsigned char pressed)
{
    unsigned char event = 0;
    /* 两个相同采样才接受新电平，滤除短时抖动。 */
    if (pressed != s->candidate) {
        s->candidate = pressed;
        s->debounce = 1;
    } else if (s->debounce < 2) s->debounce++;
    if (s->debounce < 2) return 0;
    if (pressed == 0) {
        if (s->armed && s->fired == 0) event = s->held_key;
        /* 确认松手后才重新允许触发；上电按住不会启动。 */
        s->armed = 1;
        s->fired = 0;
        s->hold_ticks = 0;
        s->held_key = 0;
    } else if (s->armed && s->fired == 0) {
        /* 只接受单个键；换键或多键同时按下不能拼接累计长按时间。 */
        if ((pressed != 1 && pressed != 2 && pressed != 4) ||
            (s->held_key && s->held_key != pressed)) {
            s->hold_ticks = 0;
            s->held_key = 0;
            s->fired = 1;
            return 0;
        }
        if (s->held_key != pressed) {
            s->hold_ticks = 0;
            s->held_key = pressed;
        }
        if (s->hold_ticks < 300) s->hold_ticks++;
        if (s->hold_ticks == 300) {
            event = KEY_LONG | pressed;
            s->fired = 1;
        }
    }
    return event;
}
#endif
