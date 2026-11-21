/*
 * LB_ISP_TEST001：专门用于串口下载验证的诊断程序。
 * 前置条件：本板型号/电平/供电已确认，电机等执行器与主板断开。
 * 不继承原厂产品功能；用户已单独授权制作烧录试验固件。
 * 本程序不配置应用GPIO、不启动电机、蜂鸣器、灯或WiFi通信。
 * 不配置GPIO不能证明外部驱动关闭，必须先做物理隔离。
 */
volatile unsigned long g_isp_test_signature;
volatile unsigned long g_isp_test_counter;

void main(void)
{
    /* 内存标记只用于标识诊断程序，不表示任何硬件已经通过测试。 */
    g_isp_test_signature = 0x49535001UL;
    g_isp_test_counter = 0UL;

    for (;;) {
        /* 只增加内存计数；计数不是毫秒，不启用中断或外设。 */
        g_isp_test_counter++;
    }
}
