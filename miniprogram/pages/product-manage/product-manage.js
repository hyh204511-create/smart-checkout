const API = require('../../utils/api');

Page({
    data: {
        products: [],
        keyword: '',
        showModal: false,
        editId: null,
        form: { name: '', price: '', cost_price: '', stock: '' },
    },
    onShow() { this.loadData(); },
    onSearch(e) { this.setData({ keyword: e.detail.value }); },
    async loadData() {
        try {
            const data = await API.getProducts();
            if (data.success) {
                let list = data.products || [];
                if (this.data.keyword) {
                    list = list.filter(p => p.name.includes(this.data.keyword));
                }
                this.setData({ products: list });
            }
        } catch (err) {
            wx.showToast({ title: '加载失败', icon: 'none' });
        }
    },
    showAdd() {
        this.setData({ showModal: true, editId: null, form: { name: '', price: '', cost_price: '', stock: '' } });
    },
    showEdit(e) {
        const item = e.currentTarget.dataset.item;
        this.setData({
            showModal: true, editId: item.id,
            form: { name: item.name, price: String(item.price), cost_price: String(item.cost_price), stock: String(item.stock) },
        });
    },
    onField(e) {
        const field = e.currentTarget.dataset.field;
        this.setData({ ['form.' + field]: e.detail.value });
    },
    closeModal() { this.setData({ showModal: false }); },
    async saveProduct() {
        const { form, editId } = this.data;
        if (!form.name) { wx.showToast({ title: '请输入商品名称', icon: 'none' }); return; }
        try {
            if (editId) {
                await API.updateProduct(editId, form);
            } else {
                await API.addProduct(form);
            }
            wx.showToast({ title: '保存成功' });
            this.setData({ showModal: false });
            this.loadData();
        } catch (err) {
            wx.showToast({ title: '保存失败: ' + err.message, icon: 'none' });
        }
    },
    async deleteProduct(e) {
        const id = e.currentTarget.dataset.id;
        const res = await new Promise(r => wx.showModal({ title: '确认删除', content: '删除后所有终端将同步', success: r }));
        if (res.confirm) {
            try {
                await API.deleteProduct(id);
                wx.showToast({ title: '已删除' });
                this.loadData();
            } catch (err) {
                wx.showToast({ title: '删除失败', icon: 'none' });
            }
        }
    },
});
