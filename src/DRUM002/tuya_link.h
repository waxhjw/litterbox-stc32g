/* 涂鸦 Wi-Fi MCU 协议连续字节解析。DP22 只由主板工作状态生成。 */
#ifndef TUYA_LINK_H
#define TUYA_LINK_H

#define DP_STATUS_MASK 7U
#define DP_APP_OUTPUT 8U
#define DP_PAUSE_APPLIED 16U
#define DP_AUTO_ACTIVE 32U
#define DP_STANDBY 0U
#define DP_WAITING 2U
#define DP_CLEANING 3U

static unsigned char frame_step, frame_cmd, frame_left, frame_len, frame_sum, frame_value;
static unsigned char link_heartbeat, link_product, link_mode, link_network=0xFF;
static unsigned char link_net_reports, link_pair, link_query, link_dp, link_errors;
static unsigned char edata dp_payload[128];
static unsigned char dp_last_id, dp_last_value, dp_changes, dp_reports, dp_invalid;
static unsigned char dp_manual_level, dp_report_pending, dp_auto_seen;
static volatile unsigned char dp_auto_level;
static volatile unsigned char dp_paused, app_start_pending;

static void wifi_frame_start(unsigned char cmd, unsigned char length);
static void wifi_frame_data(unsigned char value);
static unsigned char wifi_frame_end(void);
static void wifi_product_info(void);

static void wifi_send(unsigned char cmd)
{
    wifi_frame_start(cmd,0);
    wifi_frame_end();
}

static void wifi_bool(unsigned char dp, unsigned char value)
{
    wifi_frame_data(dp);
    wifi_frame_data(1); /* Bool，长度 1。 */
    wifi_frame_data(0);
    wifi_frame_data(1);
    wifi_frame_data(value);
}

static unsigned char wifi_report_state(unsigned char report)
{
    /* 旧面板按键沿用之前的 DP1/DP5 报告。DP22 单独上报。 */
    wifi_frame_start(7,10);
    wifi_bool(1,(report & DP_APP_OUTPUT) != 0);
    wifi_bool(5,(report & DP_PAUSE_APPLIED) != 0);
    if (!wifi_frame_end()) return 0;
    wifi_frame_start(7,5);
    wifi_frame_data(22);
    wifi_frame_data(4); /* Enum，长度 1，值为产品定义的零起始序号。 */
    wifi_frame_data(0);
    wifi_frame_data(1);
    wifi_frame_data(report & DP_STATUS_MASK);
    if (!wifi_frame_end()) return 0;
    /* 实际收到过 DP12 后回报有效开关。板载占用来源未验收时始终回报关闭。 */
    if (dp_auto_seen) {
        wifi_frame_start(7,5);
        wifi_bool(12,(report & DP_AUTO_ACTIVE)!=0);
        if (!wifi_frame_end()) return 0;
    }
    dp_reports++;
    return 1;
}

static void wifi_handle_dp(void)
{
    unsigned char offset=0, id, type, size, pending=0xFF;
    unsigned char manual=0xFF, automatic=0xFF;
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
        if (id==1) {
            if (type!=1 || manual!=0xFF) goto invalid;
            manual=last_value;
        }
        if (id==12) {
            if (type!=1 || automatic!=0xFF) goto invalid;
            automatic=last_value;
        }
        offset+=size;
    }
    dp_last_id=last_id;
    dp_last_value=last_value;
    if (pending!=0xFF && pending!=dp_paused) {
        dp_paused=pending;
        dp_changes++;
        dp_report_pending=1;
    }
    if (manual!=0xFF && manual!=dp_manual_level) {
        dp_manual_level=manual;
        /* 同值重发不会重新启动。释放值用于下一次有效按下。 */
        if (manual) {
            if (!dp_paused && link_network==4) app_start_pending=1;
            dp_report_pending=1;
        }
    }
    if (automatic!=0xFF) {
        dp_auto_level=automatic && drum_config_ready(&drum_board);
        dp_auto_seen=1;
        dp_report_pending=1;
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
            dp_report_pending=1;
            break;
        }
    } else if (frame_cmd==3 && frame_len==1 && frame_value<=6) {
        if (link_network!=4 && frame_value==4) dp_report_pending=1;
        if (frame_value!=4) app_start_pending=0;
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
