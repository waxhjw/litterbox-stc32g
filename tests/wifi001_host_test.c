#include <assert.h>
#include <string.h>
#ifdef WIFI002_TEST
#define edata
#include "../diagnostics/WIFI002/tuya_link.h"
#else
#include "../diagnostics/WIFI001/tuya_link.h"
#endif

static unsigned char response[16], response_size;

static void wifi_frame_data(unsigned char value)
{
    assert(response_size<sizeof(response));
    response[response_size++]=value;
}

static void wifi_frame_start(unsigned char cmd, unsigned char length)
{
    response_size=0;
    wifi_frame_data(0x55);
    wifi_frame_data(0xAA);
    wifi_frame_data(3);
    wifi_frame_data(cmd);
    wifi_frame_data(0);
    wifi_frame_data(length);
}

static void wifi_frame_end(void)
{
    unsigned int i;
    unsigned char sum=0;
    for (i=0;i<response_size;i++) sum+=response[i];
    wifi_frame_data(sum);
}

static void wifi_product_info(void) { wifi_send(1); }

static void receive(const char *s, unsigned int length)
{
    unsigned int i;
    response_size=0;
    for (i=0;i<length;i++) wifi_feed((unsigned char)s[i]);
}

#define IN(bytes) receive(bytes,sizeof(bytes)-1)

int main(void)
{
    /* 尚无串口会话时，配网不发出；坏校验和超长声明不得改变状态。 */
    wifi_pair();
    assert(response_size==0);
    IN("\x55\xAA\x00\x00\x00\x00\xFE");
    IN("\x55\xAA\x00\x00\x01\x00");
    assert(link_heartbeat==0 && link_errors==2 && response_size==0);
    /* 官方心跳、产品查询、工作模式和联网状态报文。 */
    IN("\x55\x55\xAA\x00\x00\x00\x00\xFF");
    assert(response_size==8 && !memcmp(response,"\x55\xAA\x03\x00\x00\x01\x00\x03",8));
    IN("\x55\xAA\x00\x00\x00\x00\xFF");
    assert(response_size==8 && !memcmp(response,"\x55\xAA\x03\x00\x00\x01\x01\x04",8));
    IN("\x55\xAA\x00\x01\x00\x00\x00");
    assert(link_product==1 && response[3]==1);
    IN("\x55\xAA\x00\x02\x00\x00\x01");
    assert(link_mode==1 && response_size==7 && response[3]==2);
    IN("\x55\xAA\x00\x03\x00\x01\x04\x07");
    assert(link_network==4 && link_net_reports==1 && response_size==7 && response[3]==3);
    /* 一次显式请求之后等待应答，重复调用不会重发。 */
    wifi_pair();
    assert(link_pair==1 && response_size==7 && response[3]==4 && response[6]==6);
    response_size=0;
    wifi_pair();
    assert(response_size==0);
    IN("\x55\xAA\x00\x04\x00\x00\x03");
    assert(link_pair==2 && response_size==0);
    IN("\x55\xAA\x00\x08\x00\x00\x07");
#ifdef WIFI002_TEST
    assert(link_query==1 && response_size==12 && response[3]==7 && response[6]==5 && response[10]==0);
    IN("\x55\xAA\x00\x06\x00\x05\x05\x01\x00\x01\x01\x12");
    assert(link_dp==1 && dp_paused==1 && dp_changes==1 && response[10]==1);
    IN("\x55\xAA\x00\x06\x00\x05\x05\x01\x00\x01\x01\x12");
    assert(response_size==0 && dp_changes==1);
    /* 连在同一帧的其它 Bool 只记录，DP5 负责改变暂停状态。 */
    IN("\x55\xAA\x00\x06\x00\x0A\x05\x01\x00\x01\x00\x01\x01\x00\x01\x01\x1A");
    assert(dp_paused==0 && dp_changes==2 && dp_last_id==1 && dp_last_value==1 && response[10]==0);
    /* DP5 后紧跟半截数据，整帧拒绝并保留已提交值。 */
    IN("\x55\xAA\x00\x06\x00\x06\x05\x01\x00\x01\x01\x01\x14");
    assert(dp_invalid==1 && dp_paused==0 && dp_changes==2 && response_size==0);
    IN("\x55\xAA\x00\x06\x00\x05\x05\x04\x00\x01\x01\x15");
    assert(dp_invalid==2 && dp_paused==0 && response_size==0);
#else
    assert(link_query==1 && response_size==0);
    IN("\x55\xAA\x00\x06\x00\x01\x01\x07");
    assert(link_dp==1 && response_size==0);
#endif
    return 0;
}
