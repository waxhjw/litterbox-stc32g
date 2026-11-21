/* 单路红外接收为高脉冲。固定高/低或没有对应发射时窗的脉冲均不能放行。 */
#ifndef SINGLE_IR_H
#define SINGLE_IR_H

enum SingleIrState { SINGLE_UNKNOWN, SINGLE_CLEAR, SINGLE_INVALID };
typedef struct {
    unsigned char state, quiet, samples, high, edges, first, last;
} SingleIr;

static void single_ir_open(volatile SingleIr *s, unsigned char level)
{
    s->quiet=(level==0);
    s->samples=0;
    s->high=0;
    s->edges=0;
    s->first=0xFF;
    s->last=level;
}

static void single_ir_sample(volatile SingleIr *s, unsigned char level)
{
    if (level) {
        s->high++;
        if (s->first==0xFF) s->first=s->samples;
    }
    if (s->last!=level) s->edges++;
    s->last=level;
    s->samples++;
}

static void single_ir_close(volatile SingleIr *s)
{
    /* 约 105us 一次，沿用早期单路实测的高有效极性与脉冲边沿判据。 */
    s->state=(s->quiet && s->last==0 && s->first<29 &&
        s->high>=2 && s->high<=48 && s->edges>=2 && s->edges<=8) ? SINGLE_CLEAR : SINGLE_INVALID;
}
#endif
