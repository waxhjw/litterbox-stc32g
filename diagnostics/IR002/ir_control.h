/* IR001原始输入统计。100us一次采样；不把RAW电平解释成有猫/无猫。 */
#ifndef IR_CONTROL_H
#define IR_CONTROL_H
typedef struct {
    unsigned char mode;       /* 0关闭，1/2/3分别为36/38/40kHz。 */
    unsigned char phase;      /* 100个采样为10ms，每周期只开前10个采样。 */
    unsigned char last_level;
    unsigned char gate;
    unsigned int cycles_left; /* 每次命令最多10秒，到期自动关闭。 */
    unsigned int samples;
    unsigned int low;
    unsigned int edges;
} IrControl;

static void ir_control_clear_stats(volatile IrControl *s)
{
    s->samples = 0;
    s->low = 0;
    s->edges = 0;
}
static void ir_control_init(volatile IrControl *s, unsigned char level)
{
    s->mode = 0;
    s->phase = 0;
    s->gate = 0;
    s->cycles_left = 0;
    s->last_level = level;
    ir_control_clear_stats(s);
}
static void ir_control_command(volatile IrControl *s, unsigned char mode)
{
    s->mode = mode <= 3 ? mode : 0;
    s->phase = 0;
    s->gate = 0;
    s->cycles_left = s->mode ? 1000 : 0;
}
static void ir_control_tick(volatile IrControl *s, unsigned char level)
{
    s->samples++;
    if (level == 0) s->low++;
    if (level != s->last_level) s->edges++;
    s->last_level = level;
    s->gate = (s->mode != 0 && s->phase < 10) ? 1 : 0;
    s->phase++;
    if (s->phase == 100) {
        s->phase = 0;
        if (s->cycles_left != 0) {
            s->cycles_left--;
            if (s->cycles_left == 0) {
                s->mode = 0;
                s->gate = 0;
            }
        }
    }
}
#endif
