/* 100us中断节拍：每次探测最多5ms，起点之间至少100ms；关机取消不清冷却。 */
#ifndef ARRAY_PROBE_STATE_H
#define ARRAY_PROBE_STATE_H
#define ARRAY_PROBE_TICKS 50U
#define ARRAY_PROBE_COOLDOWN 1000U
typedef struct {
    unsigned char active, ticks;
    unsigned short cooldown;
} ArrayProbe;
static void array_probe_init(volatile ArrayProbe *s)
{
    s->active=0; s->ticks=0; s->cooldown=0;
}
static void array_probe_cancel(volatile ArrayProbe *s)
{
    s->active=0; s->ticks=0;
}
static unsigned char array_probe_begin(volatile ArrayProbe *s,unsigned char command_id,unsigned char requested)
{
    if (requested || command_id<1 || command_id>6 || s->cooldown) return 0;
    s->active=command_id; s->ticks=ARRAY_PROBE_TICKS; s->cooldown=ARRAY_PROBE_COOLDOWN;
    return 1;
}
static unsigned char array_probe_tick(volatile ArrayProbe *s)
{
    if (s->cooldown) s->cooldown--;
    if (s->ticks) {
        s->ticks--;
        if (s->ticks==0) { s->active=0; return 1; }
    }
    return 0;
}
#endif
