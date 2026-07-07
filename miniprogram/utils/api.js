/**
 * 云端 API 封装
 */
const app = getApp();

const BASE_URL = app.globalData.serverUrl;

/**
 * 封装 wx.request
 */
function request(path, method = 'GET', data = {}) {
    const token = wx.getStorageSync('token');
    return new Promise((resolve, reject) => {
        wx.request({
            url: BASE_URL + path,
            method,
            data,
            header: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
            },
            success(res) {
                if (res.statusCode === 200) {
                    resolve(res.data);
                } else if (res.statusCode === 401) {
                    // Token 过期，跳转登录
                    wx.removeStorageSync('token');
                    wx.reLaunch({ url: '/pages/login/login' });
                    reject(new Error('未登录'));
                } else {
                    reject(new Error(res.data?.error || '请求失败'));
                }
            },
            fail(err) {
                reject(new Error('网络错误: ' + err.errMsg));
            }
        });
    });
}

// ==================== 设备管理 ====================
const API = {
    // 微信登录 (正式)
    wxLogin(code) {
        return request('/api/wx/login/', 'POST', { code });
    },

    // 调试登录 (本地测试，跳过微信校验)
    debugLogin() {
        return request('/api/wx/login/debug/', 'POST', {});
    },

    // 仪表板数据
    getDashboard() {
        return request('/api/stats/dashboard/');
    },

    // 设备列表
    getDevices() {
        return request('/api/device/list/');
    },

    // 设备详情
    getDeviceDetail(deviceId) {
        return request(`/api/device/${deviceId}/detail/`);
    },

    // 设备重命名
    renameDevice(deviceId, name) {
        return request(`/api/device/${deviceId}/rename/`, 'POST', { name });
    },

    // 订单汇总
    getOrderSummary(params = {}) {
        let query = '';
        if (params.date_from) query += `&date_from=${params.date_from}`;
        if (params.date_to) query += `&date_to=${params.date_to}`;
        if (params.device_id) query += `&device_id=${params.device_id}`;
        if (query) query = '?' + query.substring(1);
        return request('/api/order/summary/' + query);
    },

    // 商品列表
    getProducts(category = '', keyword = '') {
        return request('/api/product/cloud/', 'GET');
    },

    // 新增商品
    addProduct(data) {
        return request('/api/product/cloud/', 'POST', data);
    },

    // 修改商品
    updateProduct(id, data) {
        return request(`/api/product/cloud/${id}/`, 'PUT', data);
    },

    // 删除商品
    deleteProduct(id) {
        return request(`/api/product/cloud/${id}/`, 'DELETE');
    },
};

module.exports = API;
