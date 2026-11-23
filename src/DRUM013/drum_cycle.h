/* 滚筒行程与自动清理逻辑。每约 10 ms 调用一次，可用主机模拟位置和保护输入。 */
#ifndef DRUM_CYCLE_H
#define DRUM_CYCLE_H

#define DRUM_STOP 0U
#define DRUM_FORWARD 4U
#define DRUM_REVERSE 1U
#define DRUM_BETWEEN_MARKERS 3U
#define DRUM_POSITION_UNKNOWN 0xFFU
#define DRUM_STABLE_SAMPLES 3U
#define DRUM_DIRECTION_GAP 20U
#define DRUM_CLEAR_START 5U
/* 每个控制节拍约 9.965ms，502 个有效节拍约 5 秒。 */
#define DRUM_CLEAR_RESUME 502U

enum DrumPhase { DRUM_IDLE, DRUM_TO_DUMP, DRUM_SETTLE, DRUM_TO_HOME };
enum DrumFault {
    DRUM_OK, DRUM_UNCOMMISSIONED, DRUM_POSITION, DRUM_RADAR,
    DRUM_TIMEOUT, DRUM_DRIVE, DRUM_PRESENCE, DRUM_CANCELED, DRUM_BIN
};

#define DRUM_RADAR_CLEAR 1U
#define DRUM_LIGHT_CLEAR 2U
#define DRUM_PAUSED 4U
#define DRUM_PRESENCE_VALID 8U
#define DRUM_OCCUPIED 16U
#define DRUM_DRIVE_OK 32U
#define DRUM_BIN_READY 64U
#define DRUM_SINGLE_CLEAR 128U
#define DRUM_ENV_CLEAR (DRUM_RADAR_CLEAR|DRUM_LIGHT_CLEAR|DRUM_SINGLE_CLEAR)

typedef struct {
    unsigned char verified, home, dump, outbound, inbound;
    unsigned short outbound_limit, dump_dwell, inbound_limit, cycle_limit;
} DrumConfig;

typedef struct {
    unsigned char phase, output, fault, sample, stable, sample_count;
    unsigned char departed, started, target_seen;
    unsigned short phase_left, cycle_left, light_ticks, completed;
} DrumCycle;

typedef struct {
    unsigned char seen_occupancy;
    unsigned short clear_ticks;
} DrumAuto;

static unsigned char drum_config_ready(const DrumConfig *cfg)
{
    return cfg->verified && cfg->home < DRUM_BETWEEN_MARKERS
        && cfg->dump < DRUM_BETWEEN_MARKERS && cfg->home != cfg->dump
        && (cfg->outbound == DRUM_FORWARD || cfg->outbound == DRUM_REVERSE)
        && (cfg->inbound == DRUM_FORWARD || cfg->inbound == DRUM_REVERSE)
        && cfg->outbound_limit && cfg->inbound_limit
        && cfg->dump_dwell >= DRUM_DIRECTION_GAP
        && cfg->cycle_limit > DRUM_CLEAR_RESUME;
}

static void drum_sample(volatile DrumCycle *s, unsigned char position)
{
    /* 连续三个相同样本才确认位置。第一次看到限位就先撤销对应方向输出。 */
    if (position != s->sample) {
        s->sample = position;
        s->sample_count = 0;
    }
    if (s->sample_count < DRUM_STABLE_SAMPLES) s->sample_count++;
    if (s->sample_count == DRUM_STABLE_SAMPLES) s->stable = position;
}

static void drum_stop(volatile DrumCycle *s, unsigned char fault)
{
    s->output = DRUM_STOP;
    s->phase = DRUM_IDLE;
    s->fault = fault;
    s->cycle_left = 0;
}

static unsigned char drum_request(volatile DrumCycle *s, const DrumConfig *cfg,
                                  unsigned char input)
{
    if (s->phase != DRUM_IDLE || (input & DRUM_PAUSED)) return 0;
    if (s->fault == DRUM_POSITION || s->fault == DRUM_TIMEOUT || s->fault == DRUM_DRIVE)
        return 0; /* 位置、超时和驱动故障须在本机确认。 */
    s->fault = DRUM_OK;
    if (drum_config_ready(cfg) == 0) s->fault = DRUM_UNCOMMISSIONED;
    else if ((input & DRUM_BIN_READY) == 0) s->fault = DRUM_BIN;
    else if (s->sample_count != DRUM_STABLE_SAMPLES || s->stable != cfg->home)
        s->fault = DRUM_POSITION;
    else if ((input & DRUM_RADAR_CLEAR) == 0) s->fault = DRUM_RADAR;
    else if ((input & (DRUM_PRESENCE_VALID | DRUM_OCCUPIED)) != DRUM_PRESENCE_VALID)
        s->fault = DRUM_PRESENCE;
    else if ((input & DRUM_DRIVE_OK) == 0) s->fault = DRUM_DRIVE;
    if (s->fault != DRUM_OK) return 0;

    s->phase = DRUM_TO_DUMP;
    s->phase_left = cfg->outbound_limit;
    s->cycle_left = cfg->cycle_limit;
    s->departed = 0;
    s->started = 0;
    s->target_seen = 0;
    s->light_ticks = 0;
    return 1;
}

static void drum_tick(volatile DrumCycle *s, const DrumConfig *cfg,
                      unsigned char position, unsigned char input)
{
    unsigned char origin, target;
    unsigned short clear_required;
    s->output = DRUM_STOP;
    drum_sample(s, position);
    if (s->phase == DRUM_IDLE) return;
    if ((input & DRUM_BIN_READY) == 0) {
        drum_stop(s, DRUM_BIN);
        return;
    }
    if (position > DRUM_BETWEEN_MARKERS) {
        drum_stop(s, DRUM_POSITION);
        return;
    }
    if ((input & DRUM_DRIVE_OK) == 0) {
        drum_stop(s, DRUM_DRIVE);
        return;
    }
    if ((input & DRUM_PRESENCE_VALID) == 0) {
        drum_stop(s, DRUM_PRESENCE);
        return;
    }
    if (s->started == 0 && --s->cycle_left == 0) {
        drum_stop(s, DRUM_TIMEOUT);
        return;
    }
    /* 首次起转前原点必须一直成立。起转后允许经独立位置输入确认的中间区间。 */
    if (s->started == 0 && position != cfg->home) {
        drum_stop(s, DRUM_POSITION);
        return;
    }
    if (input & DRUM_OCCUPIED || (input & DRUM_ENV_CLEAR) != DRUM_ENV_CLEAR) {
        s->light_ticks = 0;
        return;
    }
    clear_required = s->started ? DRUM_CLEAR_RESUME : DRUM_CLEAR_START;
    if (s->light_ticks < clear_required) s->light_ticks++;
    if (s->light_ticks < clear_required || (input & DRUM_PAUSED)) return;
    if (s->started && --s->cycle_left == 0) {
        drum_stop(s, DRUM_TIMEOUT);
        return;
    }

    if (s->phase == DRUM_SETTLE) {
        if (position != cfg->dump) {
            drum_stop(s, DRUM_POSITION);
        } else if (--s->phase_left == 0) {
            s->phase = DRUM_TO_HOME;
            s->phase_left = cfg->inbound_limit;
            s->departed = 0;
            s->target_seen = 0;
        }
        return;
    }
    origin = s->phase == DRUM_TO_DUMP ? cfg->home : cfg->dump;
    target = s->phase == DRUM_TO_DUMP ? cfg->dump : cfg->home;
    if (--s->phase_left == 0) {
        drum_stop(s, DRUM_TIMEOUT);
    } else if (position == target) {
        s->target_seen = 1;
        if (s->sample_count < DRUM_STABLE_SAMPLES) return;
        if (s->departed == 0) {
            drum_stop(s, DRUM_POSITION);
        } else if (s->phase == DRUM_TO_DUMP) {
            s->phase = DRUM_SETTLE;
            s->phase_left = cfg->dump_dwell;
        } else {
            s->completed++;
            drum_stop(s, DRUM_OK);
        }
    } else if (s->target_seen) {
        /* 碰到限位后先停住；限位抖动不允许重新给电。 */
        if (s->sample_count == DRUM_STABLE_SAMPLES) drum_stop(s, DRUM_POSITION);
    } else if (position == DRUM_BETWEEN_MARKERS || (position == origin && s->departed == 0)) {
        if (position == DRUM_BETWEEN_MARKERS && s->sample_count == DRUM_STABLE_SAMPLES) s->departed = 1;
        s->output = s->phase == DRUM_TO_DUMP ? cfg->outbound : cfg->inbound;
        if (s->started == 0) {
            s->started = 1;
            /* 已连续通光，无需在首转之后额外停等。新的遮挡会把计时清零。 */
            s->light_ticks = DRUM_CLEAR_RESUME;
        }
    } else if (s->sample_count == DRUM_STABLE_SAMPLES) {
        drum_stop(s, DRUM_POSITION);
    }
}

static void drum_auto_reset(volatile DrumAuto *s)
{
    s->seen_occupancy = 0;
    s->clear_ticks = 0;
}

static unsigned char drum_auto_tick(volatile DrumAuto *s, unsigned char input,
                                    unsigned short delay_ticks)
{
    /* 必须先确认一次占用，再确认持续离开。无可信占用输入时立即取消倒计时。 */
    if ((input & DRUM_PRESENCE_VALID) == 0 || delay_ticks == 0) {
        drum_auto_reset(s);
    } else if ((input & DRUM_BIN_READY) == 0) {
        drum_auto_reset(s);
    } else if (input & DRUM_OCCUPIED) {
        s->seen_occupancy = 1;
        s->clear_ticks = 0;
    } else if ((input & DRUM_RADAR_CLEAR) == 0) {
        s->clear_ticks = 0;
    } else if (s->seen_occupancy && ++s->clear_ticks >= delay_ticks) {
        drum_auto_reset(s);
        return 1;
    }
    return 0;
}
#endif
