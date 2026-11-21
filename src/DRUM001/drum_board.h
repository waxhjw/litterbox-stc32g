/* 当前主板通路沿用 APP004。滚筒磁铁位置、驱动方向和时限必须在总成上核对。 */
#ifndef DRUM_BOARD_H
#define DRUM_BOARD_H
#include "drum_cycle.h"

/* 以下位置和行程数字供离线仿真。总成实测后在此集中替换。
 * 真实板必须独立通过位置、驱动、占用检测和保护验收后，才可设置 verified=1。 */
#define DRUM_HOME_HALL 1U
#define DRUM_DUMP_HALL 2U
#define DRUM_DUMP_DIRECTION DRUM_FORWARD
#define DRUM_HOME_DIRECTION DRUM_REVERSE
#define DRUM_DUMP_LIMIT_TICKS 2000U
#define DRUM_DUMP_DWELL_TICKS 100U
#define DRUM_HOME_LIMIT_TICKS 2000U
#define DRUM_CYCLE_LIMIT_TICKS 12000U
#define DRUM_AUTO_DELAY_TICKS 60218U
#define DRUM_MECHANICS_VERIFIED 0U
#define DRUM_SMOOTH_KEY 0U /* 实际键编号待测，0 表示未分配。 */
#define DRUM_EMPTY_KEY 0U
#define DRUM_SMOOTH_VERIFIED 0U
#define DRUM_EMPTY_VERIFIED 0U
#define DRUM_BOARD_RADAR_IDLE 0U /* 未验收极性或失效行为时，保持未确认。 */

#define DRUM_JOB_CLEAN 1U
#define DRUM_JOB_SMOOTH 2U
#define DRUM_JOB_EMPTY 3U
static const DrumConfig drum_board = {
    DRUM_MECHANICS_VERIFIED, DRUM_HOME_HALL, DRUM_DUMP_HALL, DRUM_DUMP_DIRECTION, DRUM_HOME_DIRECTION,
    DRUM_DUMP_LIMIT_TICKS, DRUM_DUMP_DWELL_TICKS, DRUM_HOME_LIMIT_TICKS, DRUM_CYCLE_LIMIT_TICKS
};
/* 平砂、倾空各有独立的目标、方向和行程时间。下列仅为模拟动作参数。 */
static const DrumConfig drum_smooth = {
    DRUM_MECHANICS_VERIFIED && DRUM_SMOOTH_VERIFIED, DRUM_HOME_HALL, 0U, DRUM_REVERSE, DRUM_FORWARD,
    1200U, 20U, 1200U, DRUM_CYCLE_LIMIT_TICKS
};
static const DrumConfig drum_empty = {
    DRUM_MECHANICS_VERIFIED && DRUM_EMPTY_VERIFIED, DRUM_HOME_HALL, 2U, DRUM_FORWARD, DRUM_REVERSE,
    2000U, 500U, 2000U, DRUM_CYCLE_LIMIT_TICKS
};

static const DrumConfig *drum_job_config(unsigned char job)
{
    if (job==DRUM_JOB_SMOOTH) return &drum_smooth;
    if (job==DRUM_JOB_EMPTY) return &drum_empty;
    return &drum_board;
}

static unsigned char drum_board_aux_inputs(void)
{
    /* 量产板称重/占用与电机保护反馈尚未定位和验收。未知输入不能当成安全。 */
    return 0;
}
#endif
