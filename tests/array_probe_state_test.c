/* 编译真实探测状态机；不访问GPIO，不代表实际5ms波形实测。 */
#include <assert.h>
#include <stdio.h>
#include "../diagnostics/IR006/array_probe_state.h"
static ArrayProbe p;
int main(void)
{
    unsigned int i,code;
    array_probe_init(&p);
    assert(array_probe_begin(&p,0,0)==0 && array_probe_begin(&p,7,0)==0);
    for(code=1;code<=6;code++) {
        array_probe_init(&p);
        assert(array_probe_begin(&p,(unsigned char)code,1)==0); /* 运行/暂停REQ1时不接受探测。 */
        assert(p.active==0);
        assert(array_probe_begin(&p,(unsigned char)code,0)==1);
        for(i=0;i<49;i++) { assert(array_probe_tick(&p)==0); assert(p.active==code); }
        assert(array_probe_tick(&p)==1 && p.active==0); /* 4.9/5ms边界。 */
        assert(array_probe_begin(&p,1,0)==0);
        array_probe_cancel(&p);
        assert(array_probe_begin(&p,1,0)==0); /* 停止命令不能绕过100ms冷却。 */
        for(i=0;i<949;i++) array_probe_tick(&p);
        assert(array_probe_begin(&p,1,0)==0);
        array_probe_tick(&p); assert(array_probe_begin(&p,1,0)==1);
        array_probe_cancel(&p); assert(p.active==0 && p.ticks==0);
    }
    array_probe_init(&p);
    assert(array_probe_begin(&p,3,0)==1);
    for(i=0;i<10;i++) array_probe_tick(&p);
    array_probe_cancel(&p);
    for(i=0;i<5000;i++) array_probe_tick(&p);
    assert(p.active==0 && p.ticks==0 && p.cooldown==0); /* 长时间空闲不溢出重开。 */
    puts("PASS: all six pin probes, run rejection, 5ms limit, 100ms cooldown, cancel, idle");
    return 0;
}
