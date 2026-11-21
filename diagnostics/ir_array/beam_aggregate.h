/* 三路有效信号的组合层；不把GPIO高低或ADC原始码直接猜成通光。
 * 输入位0/1/2分别为第1/2/3路，须先由本组模块实测得到valid/clear。
 * 返回值与既有MotorIrGuard一致：0未知，1全部通光，2至少一路遮挡。
 */
#ifndef BEAM_AGGREGATE_H
#define BEAM_AGGREGATE_H
#define IR_ARRAY_CHANNELS_MASK 7U
static unsigned char ir_array_beam(unsigned char valid, unsigned char clear)
{
    /* 缺失任一有效判定则组合状态未知，未知不能声称三路畅通。 */
    if ((valid & IR_ARRAY_CHANNELS_MASK)!=IR_ARRAY_CHANNELS_MASK) return 0;
    return (clear & IR_ARRAY_CHANNELS_MASK)==IR_ARRAY_CHANNELS_MASK ? 1 : 2;
}
#endif
