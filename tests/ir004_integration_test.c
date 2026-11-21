/* 编译IR004实际头文件；对射波形为回放输入，不能替代实物验证。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/IR004/motor_control.h"
#include "../diagnostics/IR004/ir_control.h"
#include "../diagnostics/IR004/motor_ir_guard.h"
static MotorControl motor;
static IrControl ir;
static MotorIrGuard guard;
static void reset(void)
{
    motor_control_init(&motor); ir_control_init(&ir,0); motor_ir_guard_init(&guard);
}
/* 一次10ms：真实100us接收采样、真实按键逻辑、真实联动逻辑。 */
static void cycle(unsigned char pressed, unsigned char width, unsigned char start,
                  unsigned char high_pulse)
{
    unsigned int i;
    for(i=0;i<100;i++) {
        unsigned char pulse=(i>=start && i<start+width) ? 1 : 0;
        ir_control_tick(&ir,high_pulse ? pulse : (unsigned char)(pulse==0));
    }
    motor_control_tick(&motor,pressed);
    motor_ir_guard_tick(&guard,motor.running,ir.beam);
    if(ir.samples>=5000) ir_control_clear_stats(&ir);
}
static void cycles(unsigned char key,unsigned int n,unsigned char width)
{
    while(n--) cycle(key,width,10,0);
}
static void start(unsigned char key)
{
    cycles(0,5,100); cycles(key,301,100);
    assert(motor.running==1 && guard.actual==1 && guard.armed==0);
    ir_control_command(&ir,4); /* MCU主循环在按键请求变化时配置载波；外设写入另查源码/实板。 */
}
int main(void)
{
    unsigned int i,mode,on;
    reset(); cycles(1,1000,100);
    assert(motor.running==0 && guard.actual==0 && ir.mode==0); /* 上电按住不启动。 */
    cycles(0,5,100); cycles(1,299,100); assert(motor.running==0);
    cycles(0,5,100); cycles(1,200,100); cycles(0,5,100); cycles(1,200,100);
    assert(motor.running==0); /* 短按不累积。 */
    cycles(0,5,100); cycles(3,1000,100); assert(motor.running==0);
    cycles(0,5,100); cycles(1,200,100); cycles(2,200,100); assert(motor.running==0);
    for(mode=1;mode<=4;mode*=2) {
        reset(); start((unsigned char)mode);
        cycles((unsigned char)mode,1500,100); /* 未连接导致固定低，持续按住不重复开关。 */
        assert(guard.actual==1 && guard.armed==0 && motor.running==1);
        cycles(0,100,0); assert(guard.actual==1 && guard.armed==0); /* 固定高也不冒充通光。 */
    }
    cycles(0,5,10); assert(guard.armed==1 && guard.actual==1 && ir.beam==IR_CLEAR);
    cycles(0,1,0); assert(guard.actual==0 && guard.clear_ticks_left==1000);
    cycles(0,2000,0); assert(guard.actual==0 && guard.clear_ticks_left==1000);
    assert(ir.mode==4); /* 暂停期间载波仍开启，才能检测何时移开遮挡。 */
    cycles(0,999,10); assert(guard.actual==0 && guard.clear_ticks_left==1);
    cycles(0,1,10); assert(guard.actual==1 && guard.clear_ticks_left==0);
    cycles(0,1,0); cycles(0,900,10); cycles(0,1,0);
    cycles(0,999,10); assert(guard.actual==0); cycles(0,1,10); assert(guard.actual==1);
    cycles(0,1,0); cycles(4,301,10); assert(motor.running==0 && guard.actual==0 && guard.armed==0);
    ir_control_command(&ir,0); cycles(0,1500,10); assert(guard.actual==0 && ir.gate==0);
    start(2); cycles(0,10,100); assert(guard.actual==1 && guard.armed==0); /* 重新开机重新识别。 */
    cycles(0,1,10); cycles(0,1,100); assert(guard.actual==0); /* 已建立光路后失联必须暂停。 */
    cycles(0,999,10); motor_ir_guard_tick(&guard,1,IR_UNKNOWN);
    assert(guard.actual==0 && guard.clear_ticks_left==1000); /* 未知不计入通光时间。 */
    motor_control_stop(&motor); motor_ir_guard_tick(&guard,0,IR_UNKNOWN); ir_control_command(&ir,0);
    assert(guard.actual==0 && guard.armed==0); /* 串口停止取消恢复。 */
    /* 继承独立发射诊断的三种模式、包宽、截止时间和非法命令关闭。 */
    for(mode=1;mode<=3;mode++) {
        ir_control_command(&ir,(unsigned char)mode); on=0;
        for(i=0;i<100;i++) { ir_control_tick(&ir,1); on+=ir.gate; }
        assert(on==10); cycles(0,999,0); assert(ir.mode==0 && ir.gate==0);
    }
    ir_control_command(&ir,4);
    cycle(0,1,10,0); assert(ir.beam==IR_TRIGGER);
    cycle(0,51,10,0); assert(ir.beam==IR_TRIGGER);
    cycle(0,10,40,0); assert(ir.beam==IR_TRIGGER);
    cycle(0,100,0,0); assert(ir.beam==IR_TRIGGER);
    cycle(0,0,0,0); assert(ir.beam==IR_TRIGGER);
    ir_control_command(&ir,5); cycle(0,10,10,1); assert(ir.beam==IR_CLEAR);
    ir_control_command(&ir,255); assert(ir.mode==0 && ir.gate==0);
    puts("PASS: IR004 boot/3-key/absent sensor/start/arm/block/10s/retrigger/manual cancel/loss/polarity/bounded tests");
    return 0;
}
