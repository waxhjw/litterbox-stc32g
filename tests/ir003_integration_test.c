/* 直接编译IR003的三份控制头文件；光路波形为输入回放，实际光电响应待测。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/IR003/ir_control.h"
#include "../diagnostics/IR003/motor_control.h"
#include "../diagnostics/IR003/motor_ir_guard.h"
static IrControl ir;
static MotorControl motor;
static MotorIrGuard guard;
static void cycle(unsigned char pressed, unsigned char width, unsigned char start)
{
    unsigned int i;
    for (i=0; i<100; i++) {
        unsigned char level=(i>=start && i<start+width) ? 0 : 1;
        ir_control_tick(&ir, level);
    }
    motor_control_tick(&motor, pressed);
    motor_ir_guard_tick(&guard, motor.running, ir.beam);
    if (ir.samples>=5000) ir_control_clear_stats(&ir);
}
static void cycles(unsigned char pressed, unsigned int n, unsigned char width)
{
    while(n--) cycle(pressed, width, 10);
}
int main(void)
{
    unsigned int i, mode, on;
    ir_control_init(&ir, 1); motor_control_init(&motor); motor_ir_guard_init(&guard);
    cycles(0, 10, 10); assert(ir.beam==0 && guard.actual==0);
    /* 保留所有原有有界发射模式及10秒自动关闭。 */
    for (mode=1; mode<=3; mode++) {
        ir_control_command(&ir, mode); on=0;
        for(i=0;i<100;i++) { ir_control_tick(&ir, 1); on+=ir.gate; }
        assert(on==10);
        cycles(0, 999, 10); assert(ir.mode==0 && ir.gate==0);
    }
    ir_control_command(&ir, 4);
    cycles(0, 5, 10); assert(ir.beam==IR_CLEAR && guard.actual==0);
    cycles(4, 301, 10); assert(motor.running==1 && guard.actual==0);
    cycles(4, 694, 10); assert(guard.actual==1); /* 上次未知后也须连续通光10秒。 */
    cycles(0, 1, 0); assert(ir.beam==IR_TRIGGER && guard.actual==0);
    cycles(0, 999, 10); assert(guard.actual==0);
    cycles(0, 1, 10); assert(guard.actual==1); /* 通光10秒恢复。 */
    cycles(0, 1, 0); cycles(0, 900, 10); cycles(0, 1, 0);
    cycles(0, 999, 10); assert(guard.actual==0);
    cycles(0, 1, 10); assert(guard.actual==1);
    cycles(0, 1, 0); cycles(4, 301, 10); assert(motor.running==0);
    cycles(0, 1200, 10); assert(guard.actual==0); /* 手动停机取消恢复。 */
    assert(ir.mode==4); /* 联动载波包持续，不受诊断模式10秒截止影响。 */
    cycle(0, 1, 10); assert(ir.beam==IR_TRIGGER); /* 100us单点毛刺不算通光。 */
    cycle(0, 51, 10); assert(ir.beam==IR_TRIGGER);
    cycle(0, 10, 40); assert(ir.beam==IR_TRIGGER); /* 与发送窗不匹配。 */
    cycle(0, 100, 0); assert(ir.beam==IR_TRIGGER); /* 固定低不算通光。 */
    cycle(0, 0, 0); assert(ir.beam==IR_TRIGGER); /* 固定高不算通光。 */
    ir_control_command(&ir, 5);
    for(i=0;i<100;i++) ir_control_tick(&ir, (i>=10 && i<20) ? 1 : 0);
    assert(ir.beam==IR_CLEAR); /* 经实测选择高有效后也可判脉冲。 */
    ir_control_command(&ir, 0); assert(ir.beam==IR_UNKNOWN && ir.gate==0);
    motor_control_stop(&motor); motor_ir_guard_tick(&guard, motor.running, ir.beam);
    assert(guard.actual==0);
    ir_control_command(&ir, 255); assert(ir.mode==0);
    puts("PASS: IR003 integrated beam, startup, 3-key control, block, 10s, retrigger, manual cancel, bounded modes, polarity");
    return 0;
}
