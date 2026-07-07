/** 工具函数 */
const util = {
    formatDate(date) {
        if (!date) return '';
        const d = new Date(date);
        const Y = d.getFullYear();
        const M = ('0' + (d.getMonth() + 1)).slice(-2);
        const D = ('0' + d.getDate()).slice(-2);
        return `${Y}-${M}-${D}`;
    },

    formatDateTime(date) {
        if (!date) return '--';
        const d = new Date(date);
        const Y = d.getFullYear();
        const M = ('0' + (d.getMonth() + 1)).slice(-2);
        const D = ('0' + d.getDate()).slice(-2);
        const h = ('0' + d.getHours()).slice(-2);
        const m = ('0' + d.getMinutes()).slice(-2);
        return `${Y}-${M}-${D} ${h}:${m}`;
    },

    formatMoney(num) {
        return '¥' + (Number(num) || 0).toFixed(2);
    },

    timeAgo(dateStr) {
        if (!dateStr) return '--';
        const now = Date.now();
        const past = new Date(dateStr).getTime();
        const diff = Math.floor((now - past) / 1000);
        if (diff < 60) return '刚刚';
        if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
        if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
        return Math.floor(diff / 86400) + '天前';
    },
};

module.exports = util;
