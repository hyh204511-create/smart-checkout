// 智能生鲜收银系统 — 店主管理小程序
App({
    onLaunch() {
        // 检查登录状态
        const token = wx.getStorageSync('token');
        if (!token) {
            wx.reLaunch({ url: '/pages/login/login' });
        }
    },
    globalData: {
        token: null,
        serverUrl: 'https://smart-checkout-265906-8-1439803189.sh.run.tcloudbase.com',
    }
});
