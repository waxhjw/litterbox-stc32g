/*
 * 三路对射的"载波窗口内取峰值 + 连续N窗确认"判定（纯逻辑，MCU与主机测试共用）。
 *
 * 实测依据（2026-11-11 IR008，150轮高密度统计）：
 *   载波关：三路中位 969/965/957，max<=984（约1.19V，暗态）
 *   载波开：三路 max 冲到 3896/3928/3904（约4.8V，近满量程）
 *   命中率 8% 恰好等于 1ms/10ms 的占空比 —— 接收输出只在发射窗口内有效。
 * 因此判定必须"在窗口内取最大值"，随机时刻读一次会漏掉整个窗口。
 *
 * IR012 变更（IR010/IR011 现场翻车后）：
 *   一次 adc_read 并不便宜（ADCTIM=0x3F 最长采样时间 + ADCCFG=0x2F 最慢分频），
 *   4轮×3路共12次转换远超1ms窗口。采样跨窗后，结果会被记到下一个窗口账上，
 *   而 sampled=1 又让 close 照常结算 —— miss 于是在 0..3 之间来回跳，永远到不了4。
 *   现场 04EE(1262) 这个介于暗/亮之间的读数，就是采样保持电容跨在窗口边上的证据。
 *   修法：用窗口序号 gen 做守卫，采样一旦跨窗立即中止，这一批不属于任何窗口；
 *   同时把轮数降到2轮、起始门槛提到55拍（约724us），让整批尽量落在窗内。
 *   另加 last[] 结算快照：'a' 报告原先打印的是实时累加器，被串口占用打断后
 *   读到的只是半截数据，不能用来诊断。
 *
 * 判据：某一路连续 BEAM_CONFIRM 个"已采样窗口"的峰值都低于 BEAM_THRESHOLD，
 * 才认定该路遮挡。未采样的窗口（主循环被串口打印占用）不参与判定，避免误报。
 * 本模块只输出判定结果，不做停机决策。
 */
#ifndef IR_BEAM_STATE_H
#define IR_BEAM_STATE_H

/* 暗态<=984、亮态>=3896，取2000：两侧余量均超过2倍。 */
#define BEAM_THRESHOLD 2000U
/* 连续4个窗口约40ms，足以滤掉单次漏采，又不影响正常反应速度。 */
#define BEAM_CONFIRM 4U
/* 剩余拍数低于此值就不开始采样：窗口共76拍，55拍约724us，
 * 留给2轮采样（约600us）足够。宁可少结算一个窗口，也不拿半窗的暗态去判定遮挡。 */
#define BEAM_START_TICKS 55U
/* 每轮开始前留的余量：一轮3次ADC约300us≈23拍，取24拍，不够就停手。 */
#define BEAM_GUARD_TICKS 24U

typedef struct {
    unsigned int peak[3];      /* 本窗口三路峰值（实时累加） */
    unsigned int last[3];      /* 最近一次结算的峰值快照，供报告读取 */
    unsigned char miss[3];     /* 连续未收到光的已采样窗口数 */
    unsigned char blocked;     /* bit0..2 对应三路已确认遮挡 */
    unsigned char in_window;   /* 1=当前处于载波发射窗口内 */
    unsigned char fresh;       /* 1=本窗口还没被主循环采样 */
    unsigned char sampled;     /* 1=本窗口采到过至少一轮 */
    unsigned char gen;         /* 窗口序号：每次open递增，用于识别采样是否跨窗 */
} IrBeam;

/* 清零：上电与每次开载波都调用，防止上一轮计数残留。 */
static void ir_beam_init(volatile IrBeam *b)
{
    b->peak[0]=0; b->peak[1]=0; b->peak[2]=0;
    b->last[0]=0; b->last[1]=0; b->last[2]=0;
    b->miss[0]=0; b->miss[1]=0; b->miss[2]=0;
    b->blocked=0; b->in_window=0; b->fresh=0; b->sampled=0; b->gen=0;
}

/* 窗口开始（ISR在burst载入那一拍调用）：清峰值、推进窗口序号、标记待采样。 */
static void ir_beam_open(volatile IrBeam *b)
{
    b->peak[0]=0; b->peak[1]=0; b->peak[2]=0;
    b->gen++;
    b->in_window=1; b->fresh=1; b->sampled=0;
}

/* 是否该开始采这一窗：本窗还没采过，且剩余拍数够放完整的一轮峰值。
 * 主循环必须经由它进入采样——只判断"窗口开过"是不够的，
 * 被报告打印拖住时窗口可能只剩尾巴，那一次的峰值比暗态还低。 */
static unsigned char ir_beam_ready(volatile IrBeam *b, unsigned char burst_ticks)
{
    return (unsigned char)(b->sampled==0 && burst_ticks>=BEAM_START_TICKS);
}

/* 主循环在窗口内累计峰值；ADC超时值0xFFFF不能当作"收到光"。 */
static void ir_beam_add(volatile IrBeam *b, unsigned int p0, unsigned int p1, unsigned int p2)
{
    if (p0!=0xFFFF && p0>b->peak[0]) b->peak[0]=p0;
    if (p1!=0xFFFF && p1>b->peak[1]) b->peak[1]=p1;
    if (p2!=0xFFFF && p2>b->peak[2]) b->peak[2]=p2;
}

/* 窗口结束（ISR在burst归零那一拍调用）：结算连续计数与遮挡位图。 */
static void ir_beam_close(volatile IrBeam *b)
{
    if (b->in_window==0) return;
    b->in_window=0; b->fresh=0;
    if (b->sampled==0) return;   /* 主循环忙没采到，本窗口不参与判定 */
    b->last[0]=b->peak[0]; b->last[1]=b->peak[1]; b->last[2]=b->peak[2];
    if (b->peak[0]<BEAM_THRESHOLD) { if (b->miss[0]<BEAM_CONFIRM) b->miss[0]++; } else b->miss[0]=0;
    if (b->peak[1]<BEAM_THRESHOLD) { if (b->miss[1]<BEAM_CONFIRM) b->miss[1]++; } else b->miss[1]=0;
    if (b->peak[2]<BEAM_THRESHOLD) { if (b->miss[2]<BEAM_CONFIRM) b->miss[2]++; } else b->miss[2]=0;
    b->blocked=(unsigned char)((b->miss[0]>=BEAM_CONFIRM?1:0)
                             | (b->miss[1]>=BEAM_CONFIRM?2:0)
                             | (b->miss[2]>=BEAM_CONFIRM?4:0));
}
#endif
