const API = require('../../utils/api');
const util = require('../../utils/util');

Page({
    data: {
        todaySales: '0.00',
        todayOrders: 0,
        onlineDevices: 0,
        totalDevices: 0,
        devices: [],
        hotProducts: [],
    },
    onShow() { this.loadData(); },
    onRefresh() {
        this.loadData().then(() => wx.stopPullDownRefresh());
    },
    async loadData() {
        try {
            const data = await API.getDashboard();
            if (data.success) {
                this.setData({
                    todaySales: (data.today_sales || 0).toFixed(2),
                    todayOrders: data.today_orders || 0,
                    onlineDevices: data.online_devices || 0,
                    totalDevices: data.total_devices || 0,
                    devices: data.devices || [],
                    hotProducts: data.hot_products || [],
                });
            }
        } catch (err) {
            wx.showToast({ title: '加载失败', icon: 'none' });
        }
    },
    goDetail(e) {
        const id = e.currentTarget.dataset.id;
        wx.navigateTo({ url: `/pages/device-detail/device-detail?deviceId=${id}` });
    },
    // 让 wxml 能访问 util
    util: util,
});
