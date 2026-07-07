const API = require('../../utils/api');
const util = require('../../utils/util');

Page({
    data: {
        deviceId: '',
        device: {},
        todaySales: '0.00',
        todayOrders: 0,
        recentOrders: [],
    },
    onLoad(options) {
        this.setData({ deviceId: options.deviceId });
        this.loadData();
    },
    async loadData() {
        try {
            const data = await API.getDeviceDetail(this.data.deviceId);
            if (data.success) {
                this.setData({
                    device: data.device || {},
                    todaySales: (data.today_sales || 0).toFixed(2),
                    todayOrders: data.today_orders || 0,
                    recentOrders: (data.recent_orders || []).slice(0, 10),
                });
            }
        } catch (err) {
            wx.showToast({ title: '加载失败', icon: 'none' });
        }
    },
    util: util,
});
