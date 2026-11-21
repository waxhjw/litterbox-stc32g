/* IR003：保留原始统计/有界发射，另加对射脉冲窗口；100us采样。 */
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
    unsigned char window_low, window_edges, first_active, beam;
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
    s->window_low=0; s->window_edges=0; s->first_active=100; s->beam=0;
    ir_control_clear_stats(s);
}
static void ir_control_command(volatile IrControl *s, unsigned char mode)
{
    s->mode = mode <= 5 ? mode : 0;
    s->phase = 0;
    s->gate = 0;
    s->cycles_left = (s->mode && s->mode<=3) ? 1000 : 0;
    s->window_low=0; s->window_edges=0; s->first_active=100; s->beam=0;
}
static void ir_control_tick(volatile IrControl *s, unsigned char level)
{
    s->samples++;
    if (level == 0) { s->low++; s->window_low++; }
    if (level != s->last_level) { s->edges++; s->window_edges++; }
    if (s->first_active==100 && level==(s->mode==5 ? 1 : 0)) s->first_active=s->phase;
    s->last_level = level;
    s->gate = (s->mode != 0 && s->phase < 10) ? 1 : 0;
    s->phase++;
    if (s->phase == 100) {
        s->phase = 0;
        /* 联动必须先由实测选定低/高有效：4=低脉冲，5=高脉冲。
         * 一周期10ms应看到200us～5ms的完整脉冲，首响应在发射后3ms内。
         * 固定高/低、过多毛刺、未验证模式都不能当作通光。
         * 门槛为本版诊断假设，须用真实无遮挡/遮挡波形回归。 */
        s->beam=0;
        if (s->mode>=4) {
            unsigned char active;
            active=s->mode==4 ? s->window_low : 100-s->window_low;
            /* 无符号减法区间判断，与2..50、2..8完全等价，减少251目标代码。 */
            s->beam=((unsigned char)(active-2)<=48 &&
                     (unsigned char)(s->window_edges-2)<=6 && s->first_active<30) ? 1 : 2;
        }
        s->window_low=0; s->window_edges=0; s->first_active=100;
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
