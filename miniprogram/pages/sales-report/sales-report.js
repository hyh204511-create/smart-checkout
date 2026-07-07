const API = require('../../utils/api');
const util = require('../../utils/util');

Page({
    data: {
        dateFrom: '',
        dateTo: '',
        totalAmount: '0.00',
        totalCount: 0,
        byDevice: [],
        byDate: [],
    },
    onLoad() {
        // 默认最近7天
        const now = new Date();
        const weekAgo = new Date(now.getTime() - 7 * 86400000);
        this.setData({
            dateFrom: util.formatDate(weekAgo),
            dateTo: util.formatDate(now),
        });
        this.loadData();
    },
    onShow() {
        this.loadData();
    },
    onDateFrom(e) { this.setData({ dateFrom: e.detail.value }); },
    onDateTo(e) { this.setData({ dateTo: e.detail.value }); },
    async loadData() {
        try {
            const params = {};
            if (this.data.dateFrom) params.date_from = this.data.dateFrom;
            if (this.data.dateTo) params.date_to = this.data.dateTo;
            const data = await API.getOrderSummary(params);
            if (data.success) {
                this.setData({
                    totalAmount: (data.total_amount || 0).toFixed(2),
                    totalCount: data.total_count || 0,
                    byDevice: data.by_device || [],
                    byDate: data.by_date || [],
                });
            }
        } catch (err) {
            wx.showToast({ title: '加载失败', icon: 'none' });
        }
    },
});
