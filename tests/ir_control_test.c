/* 真实红外状态机与电机头文件一起回放，不能替代实物红外响应。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/IR002/ir_control.h"
#include "../diagnostics/IR002/motor_control.h"
int main(void)
{
    IrControl ir;
    MotorControl motor;
    unsigned long i;
    unsigned int on, mode;
    ir_control_init(&ir, 1);
    for (i=0; i<5000; i++) ir_control_tick(&ir, 1);
    assert(ir.mode==0 && ir.gate==0 && ir.low==0 && ir.edges==0);
    assert(ir.samples==5000);
    ir_control_clear_stats(&ir);
    for (i=0; i<5000; i++) ir_control_tick(&ir, i%2);
    assert(ir.low==2500 && ir.edges==5000);
    for (mode=1; mode<=3; mode++) {
        ir_control_command(&ir, mode);
        on=0;
        for (i=0; i<100; i++) { ir_control_tick(&ir, 1); on+=ir.gate; }
        assert(on==10 && ir.cycles_left==999);
        for (i=100; i<100000; i++) {
            ir_control_tick(&ir, 1);
            if (i%5000==0) ir_control_clear_stats(&ir);
        }
        assert(ir.mode==0 && ir.gate==0 && ir.cycles_left==0);
    }
    ir_control_command(&ir, 2); ir_control_tick(&ir, 1); assert(ir.gate==1);
    ir_control_command(&ir, 0); ir_control_tick(&ir, 1); assert(ir.gate==0);
    ir_control_command(&ir, 255); assert(ir.mode==0);
    /* 100us红外采样与10ms按键任务并行，不改变长按3秒的条件。 */
    motor_control_init(&motor); ir_control_init(&ir, 1);
    for (i=0; i<500; i++) {
        ir_control_tick(&ir, 1);
        if (i%100==99) motor_control_tick(&motor, 0);
    }
    ir_control_command(&ir, 2);
    for (i=0; i<30100; i++) {
        ir_control_tick(&ir, i%2);
        if (i%100==99) motor_control_tick(&motor, 4);
        if (i%5000==0) ir_control_clear_stats(&ir);
    }
    assert(motor.running==1 && ir.mode==2);
    motor_control_stop(&motor); ir_control_command(&ir, 0);
    assert(motor.running==0 && ir.mode==0 && ir.gate==0);
    puts("PASS: IR default-off, counts, 10% envelopes, all modes, 10s timeout, stop, motor integration");
    return 0;
}
