const app = getApp();
const API = require('../../utils/api');

Page({
    data: {
        nickname: '',
        avatarUrl: '',
        serverUrl: app.globalData.serverUrl,
        onlineDevices: 0,
        totalDevices: 0,
        lowStockThreshold: 5,
    },
    onShow() {
        this.setData({
            nickname: wx.getStorageSync('nickname') || '',
            avatarUrl: wx.getStorageSync('avatarUrl') || '',
        });
        this.loadStatus();
    },
    async loadStatus() {
        try {
            const data = await API.getDashboard();
            if (data.success) {
                this.setData({
                    onlineDevices: data.online_devices || 0,
                    totalDevices: data.total_devices || 0,
                });
            }
        } catch (err) { /* ignore */ }
    },
    onThreshold(e) {
        this.setData({ lowStockThreshold: e.detail.value });
    },
    logout() {
        wx.showModal({
            title: '确认退出',
            content: '退出后需要重新登录',
            success: (res) => {
                if (res.confirm) {
                    wx.removeStorageSync('token');
                    wx.reLaunch({ url: '/pages/login/login' });
                }
            }
        });
    },
});
