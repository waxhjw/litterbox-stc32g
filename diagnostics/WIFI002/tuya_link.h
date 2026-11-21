/* 涂鸦 Wi-Fi MCU 协议连续字节解析。DP5 仅控制台架暂停状态。 */
#ifndef TUYA_LINK_H
#define TUYA_LINK_H

static unsigned char frame_step, frame_cmd, frame_left, frame_len, frame_sum, frame_value;
static unsigned char link_heartbeat, link_product, link_mode, link_network=0xFF;
static unsigned char link_net_reports, link_pair, link_query, link_dp, link_errors;
static unsigned char edata dp_payload[128];
static unsigned char dp_last_id, dp_last_value, dp_paused, dp_changes, dp_reports, dp_invalid;

static void wifi_frame_start(unsigned char cmd, unsigned char length);
static void wifi_frame_data(unsigned char value);
static void wifi_frame_end(void);
static void wifi_product_info(void);

static void wifi_send(unsigned char cmd)
{
    wifi_frame_start(cmd,0);
    wifi_frame_end();
}

static void wifi_report_pause(void)
{
    wifi_frame_start(7,5);
    wifi_frame_data(5); /* 产品 DP5，设备暂停/继续。 */
    wifi_frame_data(1); /* Bool，长度 1。 */
    wifi_frame_data(0);
    wifi_frame_data(1);
    wifi_frame_data(dp_paused);
    wifi_frame_end();
    dp_reports++;
}

static void wifi_handle_dp(void)
{
    unsigned char offset=0, id, type, size, pending=0xFF;
    unsigned char last_id=dp_last_id, last_value=dp_last_value;

    /* 先验整帧再提交状态，半截数据或错误类型无法改变台架状态。 */
    while (offset<frame_len) {
        if (frame_len-offset<4) goto invalid;
        id=dp_payload[offset++];
        type=dp_payload[offset++];
        if (dp_payload[offset++]!=0) goto invalid;
        size=dp_payload[offset++];
        if (size>frame_len-offset) goto invalid;
        if (type==1) {
            if (size!=1 || dp_payload[offset]>1) goto invalid;
            last_id=id;
            last_value=dp_payload[offset];
        }
        if (id==5) {
            if (type!=1 || pending!=0xFF) goto invalid;
            pending=last_value;
        }
        offset+=size;
    }
    dp_last_id=last_id;
    dp_last_value=last_value;
    if (pending!=0xFF && pending!=dp_paused) {
        dp_paused=pending;
        dp_changes++;
        wifi_report_pause();
    }
    return;
invalid:
    dp_invalid++;
}

static void wifi_dispatch(void)
{
    if (frame_len==0) {
        switch (frame_cmd) {
        case 0:
            wifi_frame_start(0,1);
            wifi_frame_data(link_heartbeat!=0);
            wifi_frame_end();
            if (link_heartbeat<0xFF) link_heartbeat++;
            break;
        case 1:
            link_product++;
            wifi_product_info();
            break;
        case 2:
            link_mode++;
            wifi_send(2);
            break;
        case 4:
            if (link_pair==1) link_pair=2;
            break;
        case 8:
            link_query++;
            wifi_report_pause();
            break;
        }
    } else if (frame_cmd==3 && frame_len==1 && frame_value<=6) {
        link_network=frame_value;
        link_net_reports++;
        wifi_send(3);
    } else if (frame_cmd==6) {
        link_dp++;
        wifi_handle_dp();
    }
}

static void wifi_feed(unsigned char value)
{
    switch (frame_step) {
    case 0:
        if (value==0x55) frame_step=1;
        return;
    case 1:
        if (value==0xAA) {
            frame_step=2;
            frame_sum=0xFF;
        } else if (value!=0x55) frame_step=0;
        return;
    case 2:
        if (value!=0) goto invalid; /* 模块侧基础报文版本为 0。 */
        frame_step=3;
        break;
    case 3:
        frame_cmd=value;
        frame_step=4;
        break;
    case 4:
        if (value!=0) goto invalid; /* 本轮仅需短帧，高长度字节必须为零。 */
        frame_step=5;
        break;
    case 5:
        if (value>sizeof(dp_payload)) goto invalid;
        frame_len=frame_left=value;
        frame_step=value ? 6 : 7;
        break;
    case 6:
        frame_value=value;
        if (frame_cmd==6) dp_payload[frame_len-frame_left]=value;
        if (--frame_left==0) frame_step=7;
        break;
    case 7:
        frame_step=0;
        if (frame_sum==value) wifi_dispatch();
        else link_errors++;
        return;
    }
    frame_sum+=value;
    return;
invalid:
    frame_step=(value==0x55) ? 1 : 0;
    link_errors++;
}

static void wifi_pair(void)
{
    /* 仅在串口已握手、一次人工请求时清网络，不自动重发。 */
    if (link_pair==0 && link_heartbeat && ((link_product && link_mode) || link_net_reports)) {
        link_pair=1;
        wifi_send(4);
    }
}

#endif
