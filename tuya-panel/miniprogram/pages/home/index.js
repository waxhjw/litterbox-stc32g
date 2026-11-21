const DP = { MANUAL: '1', PAUSE: '5', STATUS: '22' };
const STATUS_CODES = ['standby', 'off', 'waiting_cluster', 'cleaning', 'uv', 'deodorization', 'sleep'];
const STATUS_LABELS = ['待机中', '已关闭', '等待清理', '清理中', '除菌中', '除味中', '休眠中'];

function readValue(value) {
  return value && typeof value === 'object' ? value.value : value;
}

function readStatus(value) {
  value = readValue(value);
  const index = STATUS_CODES.indexOf(value);
  if (index !== -1) return index;
  if ((typeof value === 'number' || typeof value === 'string') && /^[0-6]$/.test(String(value))) {
    return Number(value);
  }
  return null;
}

function readBool(value) {
  value = readValue(value);
  if (value === true || value === 1 || value === 'true' || value === '1') return true;
  if (value === false || value === 0 || value === 'false' || value === '0') return false;
  return null;
}

function hasDp(dps, id) {
  return Object.prototype.hasOwnProperty.call(dps, id);
}

function isCleaning(status) {
  return status === 2 || status === 3;
}

function canStart(link) {
  return link.online === true && link.status === 0 && link.paused === false;
}

function present(link) {
  const online = link.online === true;
  const paused = link.paused === true;
  const canPause = online && link.paused !== null && (paused || isCleaning(link.status));
  let title = STATUS_LABELS[link.status] || '读取状态中';
  let description = '';

  if (link.online === false) {
    title = '设备离线';
  } else if (link.online === null) {
    title = '连接设备';
  } else if (paused && (link.status === 0 || isCleaning(link.status))) {
    title = '已暂停';
  } else if (link.status === 2) {
    description = '设备正在确认是否可以清理。';
  }

  return {
    online,
    connection: online ? '在线' : link.online === false ? '离线' : '连接中',
    title,
    description: link.message || description,
    paused,
    cleanDisabled: !canStart(link) || !!link.pending,
    pauseDisabled: !canPause || !!link.pending
  };
}

Page({
  data: present({ online: null, status: null, paused: null }),

  onLoad(query) {
    const launch = ty.getLaunchOptionsSync ? ty.getLaunchOptionsSync() : {};
    const launchQuery = (launch && launch.query) || {};
    query = query || {};
    const link = {
      id: query.deviceId || query.devId || launchQuery.deviceId || launchQuery.devId,
      online: null,
      status: null,
      paused: null,
      revision: 0,
      connectionRevision: 0,
      message: '',
      pending: null
    };
    this.link = link;
    if (!link.id) {
      link.message = '请从智能生活的设备列表打开。';
      this.setData(present(link));
      return;
    }

    const matches = (event) => this.link === link && event &&
      (event.deviceId || event.devId) === link.id;

    link.dpListener = (event) => {
      if (matches(event) && event.dps) this.applyDps(event.dps);
    };
    link.onlineListener = (event) => {
      if (!matches(event)) return;
      const online = [event.isOnline, event.online, event.status]
        .find((value) => typeof value === 'boolean');
      if (online === undefined || online === link.online) return;
      link.online = online;
      link.status = null;
      link.paused = null;
      link.connectionRevision++;
      this.finishCommand('');
      if (online) this.readDevice();
    };
    ty.device.onDpDataChange(link.dpListener);
    ty.device.onDeviceOnlineStatusUpdate(link.onlineListener);
    this.readDevice();
  },

  onShow() {
    if (this.link && this.link.id) this.readDevice();
  },

  onUnload() {
    const link = this.link;
    this.link = null;
    if (!link) return;
    if (link.pending) clearTimeout(link.pending.timer);
    if (link.dpListener) ty.device.offDpDataChange(link.dpListener);
    if (link.onlineListener) ty.device.offDeviceOnlineStatusUpdate(link.onlineListener);
  },

  readDevice() {
    const link = this.link;
    if (link.reading) return;
    const revision = link.revision;
    const connectionRevision = link.connectionRevision;
    link.reading = true;
    ty.device.getDeviceInfo({
      deviceId: link.id,
      success: (info) => {
        if (this.link !== link || connectionRevision !== link.connectionRevision) return;
        if (typeof info.isOnline === 'boolean') {
          link.online = info.isOnline;
        }
        // 在查询返回之前已有实时回报时，用回报填过的值优先。
        this.applyDps(info.dps || {}, revision !== link.revision, true);
      },
      fail: () => {
        if (this.link !== link || link.online !== null) return;
        link.message = '暂时无法读取设备，请稍后打开。';
        this.setData(present(link));
      },
      complete: () => {
        link.reading = false;
        if (this.link === link && link.online && connectionRevision !== link.connectionRevision) {
          this.readDevice();
        }
      }
    });
  },

  applyDps(dps, fillMissing, snapshot) {
    const link = this.link;
    const status = hasDp(dps, DP.STATUS);
    const pause = hasDp(dps, DP.PAUSE);
    if (status && (!fillMissing || link.status === null)) link.status = readStatus(dps[DP.STATUS]);
    if (pause && (!fillMissing || link.paused === null)) link.paused = readBool(dps[DP.PAUSE]);
    if (!snapshot && (status || pause)) link.revision++;

    const pending = link.pending;
    if (!snapshot && pending && pending.sent) {
      if (pending.kind === 'start' && status && isCleaning(link.status)) {
        this.finishCommand('');
        return;
      }
      if (pending.kind === 'pause' && pause && link.paused === pending.value) {
        this.finishCommand('');
        return;
      }
    }
    if (!pending && (status || pause) && link.status !== null) link.message = '';
    this.setData(present(link));
  },

  beginCommand(kind, value) {
    const pending = { kind, value, sent: false };
    const link = this.link;
    link.pending = pending;
    link.message = '正在发送…';
    pending.timer = setTimeout(() => {
      this.finishCommand('设备暂未确认，请查看状态。');
    }, 8000);
    this.setData(present(link));
    return pending;
  },

  finishCommand(message) {
    const link = this.link;
    if (!link) return;
    if (link.pending) clearTimeout(link.pending.timer);
    link.pending = null;
    link.message = message;
    this.setData(present(link));
  },

  publish(id, value, pending, onSuccess) {
    const link = this.link;
    const current = () => this.link === link && link.pending === pending;
    const failed = () => {
      if (current()) this.finishCommand('发送失败，请稍后再试。');
    };
    ty.device.publishDps({
      deviceId: link.id,
      dps: { [id]: value },
      mode: 1,
      pipelines: [1],
      options: {},
      success: (sent) => {
        if (!current()) return;
        if (sent === false) failed();
        else onSuccess();
      },
      fail: failed
    });
  },

  startCleaning() {
    const link = this.link;
    if (!link || link.pending || !canStart(link)) return;
    const pending = this.beginCommand('start', true);

    // 固件用 DP1 的上升沿请求清理。每次明确点击先释放旧值，再发送一次 true。
    this.publish(DP.MANUAL, false, pending, () => {
      if (!canStart(link)) {
        this.finishCommand('设备状态已变化。');
        return;
      }
      pending.sent = true;
      this.publish(DP.MANUAL, true, pending, () => {
        link.message = '等待设备确认…';
        this.setData(present(link));
      });
    });
  },

  togglePause() {
    const link = this.link;
    if (!link || present(link).pauseDisabled) return;
    const pending = this.beginCommand('pause', !link.paused);
    pending.sent = true;
    this.publish(DP.PAUSE, pending.value, pending, () => {
      link.message = '等待设备确认…';
      this.setData(present(link));
    });
  }
});
