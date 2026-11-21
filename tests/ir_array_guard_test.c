/* 三路组合接入已有IR005真实电机守卫；仅验证逻辑，不证明光电硬件。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/IR005/motor_ir_guard.h"
#include "../diagnostics/ir_array/beam_aggregate.h"
static MotorIrGuard guard;
static void feed(unsigned char request,unsigned char valid,unsigned char clear,unsigned int ticks)
{
    while(ticks--) motor_ir_guard_tick(&guard,request,ir_array_beam(valid,clear));
}
int main(void)
{
    unsigned int mask,bit;
    for(mask=0;mask<7;mask++) assert(ir_array_beam((unsigned char)mask,7)==IR_UNKNOWN);
    assert(ir_array_beam(7,7)==IR_CLEAR);
    for(mask=0;mask<7;mask++) assert(ir_array_beam(7,(unsigned char)mask)==IR_TRIGGER);
    motor_ir_guard_init(&guard); feed(0,0,0,1000); assert(guard.actual==0);
    feed(1,0,0,3000); assert(guard.actual==1 && guard.armed==0); /* 继承未接模块电机测试能力。 */
    feed(1,3,3,1000); assert(guard.armed==0); /* 少一路不能建立三路保护。 */
    feed(1,7,7,1); assert(guard.armed==1 && guard.actual==1);
    for(bit=1;bit<=4;bit*=2) {
        feed(1,7,(unsigned char)(7^bit),1); assert(guard.actual==0);
        feed(1,7,(unsigned char)(7^bit),1200); assert(guard.actual==0 && guard.clear_ticks_left==1000);
        feed(1,7,7,999); assert(guard.actual==0);
        feed(1,7,7,1); assert(guard.actual==1);
    }
    feed(1,7,6,1); feed(1,7,7,900); feed(1,7,5,1);
    feed(1,7,7,999); assert(guard.actual==0); feed(1,7,7,1); assert(guard.actual==1);
    feed(1,3,3,1); assert(guard.actual==0); /* 建立保护后，任一路失联也暂停。 */
    feed(1,7,7,900); feed(0,7,7,1500); assert(guard.actual==0 && guard.armed==0);
    puts("PASS: three channels, all-clear arm, any obstruction/loss, 9.99/10s, retrigger, manual cancel, disconnected test");
    return 0;
}
