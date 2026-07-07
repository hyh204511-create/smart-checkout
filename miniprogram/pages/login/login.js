const API = require('../../utils/api');

Page({
    data: { loading: false },
    handleLogin() {
        this.setData({ loading: true });
        // 调试模式: 直接调 debugLogin 跳过微信校验
        // 正式上线: 替换为 wx.login() → API.wxLogin(code)
        API.debugLogin().then(data => {
            if (data.success) {
                wx.setStorageSync('token', data.token);
                wx.setStorageSync('nickname', data.nickname || '');
                wx.switchTab({ url: '/pages/dashboard/dashboard' });
            } else {
                wx.showToast({ title: data.error || '登录失败', icon: 'none' });
            }
        }).catch(err => {
            wx.showToast({ title: err.message, icon: 'none' });
        }).finally(() => {
            this.setData({ loading: false });
        });
    }
});
