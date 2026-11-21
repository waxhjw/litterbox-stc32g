/* 10ms采样一次的按键逻辑；由MCU和主机测试共同编译。 */
#ifndef MOTOR_CONTROL_H
#define MOTOR_CONTROL_H
typedef struct {
    unsigned char running, candidate, stable_pressed, debounce, armed, fired;
    unsigned short hold_ticks;
} MotorControl;
static void motor_control_init(volatile MotorControl *s)
{
    s->running = 0;
    s->candidate = 1;
    s->stable_pressed = 1;
    s->debounce = 0;
    s->armed = 0;
    s->fired = 0;
    s->hold_ticks = 0;
}
static void motor_control_stop(volatile MotorControl *s)
{
    s->running = 0;
    s->armed = 0;
    s->fired = 1;
    s->hold_ticks = 0;
}
static void motor_control_tick(volatile MotorControl *s, unsigned char pressed)
{
    /* 两个相同采样才接受新电平，滤除短时抖动。 */
    if (pressed != s->candidate) {
        s->candidate = pressed;
        s->debounce = 1;
    } else if (s->debounce < 2) s->debounce++;
    if (s->debounce < 2) return;
    s->stable_pressed = s->candidate;
    if (s->stable_pressed == 0) {
        /* 确认松手后才重新允许触发；上电按住不会启动。 */
        s->armed = 1;
        s->fired = 0;
        s->hold_ticks = 0;
    } else if (s->armed && s->fired == 0) {
        if (s->hold_ticks < 300) s->hold_ticks++;
        if (s->hold_ticks == 300) {
            /* 连续长按约3秒切换一次；一直按住不会重复启停。 */
            s->running = s->running == 0;
            s->fired = 1;
        }
    }
}
#endif
