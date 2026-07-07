#include "lcd.h"
#include "font.h" 
#include "stdio.h"

// 全局变量
uint16_t LCD_W = 240; 
uint16_t LCD_H = 320; 
uint16_t POINT_COLOR = RED;
uint16_t BACK_COLOR = WHITE;
uint16_t LCD_ID = 0;  

// 延时封装
static void delay_ms(volatile uint32_t ms) {
    HAL_Delay(ms);
}

//----------------- 底层接口 -----------------
void LCD_WriteCmd(uint16_t Cmd) {
    LCD_WR_REG(Cmd);
}

void LCD_WriteData(uint16_t Data) {
    LCD_WR_DATA(Data);
}

void LCD_WriteReg(uint16_t LCD_Reg, uint16_t LCD_RegValue) {
    LCD_WR_REG(LCD_Reg);
    LCD_WR_DATA(LCD_RegValue);
}

uint16_t LCD_ReadReg(uint16_t LCD_Reg) {
    LCD_WR_REG(LCD_Reg);
    delay_ms(5); // 读操作需要一点延时
    return LCD_RD_DATA();   
}

void LCD_WriteRAM_Prepare(void) {
    LCD_WR_REG(0x2C); 
}

//----------------- 绘图功能 -----------------

// 设置光标位置
void LCD_SetCursor(uint16_t Xpos, uint16_t Ypos) {
    LCD_WR_REG(0x2A); 
    LCD_WR_DATA(Xpos >> 8); 
    LCD_WR_DATA(Xpos & 0XFF);
    
    LCD_WR_REG(0x2B); 
    LCD_WR_DATA(Ypos >> 8); 
    LCD_WR_DATA(Ypos & 0XFF);
    
    LCD_WR_REG(0x2C);
}

// 清屏
void LCD_Clear(uint16_t Color) {
    uint32_t total = LCD_W * LCD_H;
    LCD_SetCursor(0, 0);
    LCD_WriteRAM_Prepare();
    for (uint32_t i = 0; i < total; i++) {
        LCD_WR_DATA(Color);
    }
}

// 画点
void LCD_DrawPoint(uint16_t x, uint16_t y) {
    LCD_SetCursor(x, y);
    LCD_WriteRAM_Prepare();
    LCD_WR_DATA(POINT_COLOR);
}

// 画线
void LCD_DrawLine(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2) {
    uint16_t t; 
    int xerr=0,yerr=0,delta_x,delta_y,distance; 
    int incx,incy,uRow,uCol; 
    delta_x=x2-x1; 
    delta_y=y2-y1; 
    uRow=x1; 
    uCol=y1; 
    if(delta_x>0)incx=1; 
    else if(delta_x==0)incx=0;
    else {incx=-1;delta_x=-delta_x;} 
    if(delta_y>0)incy=1; 
    else if(delta_y==0)incy=0;
    else{incy=-1;delta_y=-delta_y;} 
    if( delta_x>delta_y)distance=delta_x; 
    else distance=delta_y; 
    for(t=0;t<=distance+1;t++ ) {  
        LCD_DrawPoint(uRow,uCol);
        xerr+=delta_x ; 
        yerr+=delta_y ; 
        if(xerr>distance) { 
            xerr-=distance; 
            uRow+=incx; 
        } 
        if(yerr>distance) { 
            yerr-=distance; 
            uCol+=incy; 
        } 
    }  
}

// 画矩形
void LCD_DrawRectangle(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2) {
    LCD_DrawLine(x1, y1, x2, y1);
    LCD_DrawLine(x1, y1, x1, y2);
    LCD_DrawLine(x1, y2, x2, y2);
    LCD_DrawLine(x2, y1, x2, y2);
}

// 填充矩形
void LCD_Fill(uint16_t sx, uint16_t sy, uint16_t ex, uint16_t ey, uint16_t color) {
    uint16_t i, j;
    uint16_t width = ex - sx + 1;
    uint16_t height = ey - sy + 1;
    LCD_SetCursor(sx, sy);
    LCD_WriteRAM_Prepare();
    for (i = 0; i < height; i++) {
        for (j = 0; j < width; j++) {
            LCD_WR_DATA(color);
        }
    }
}

// 显示字符
void LCD_ShowChar(uint16_t x, uint16_t y, uint8_t num, uint8_t size, uint8_t mode) {
    uint8_t temp, t1, t;
    uint16_t y0 = y;
    uint8_t csize = (size / 8 + ((size % 8) ? 1 : 0)) * (size / 2); 
    num = num - ' '; 
    for (t = 0; t < csize; t++) {
        if (size == 12) temp = asc2_1206[num][t];      
        else if (size == 16) temp = asc2_1608[num][t]; 
        else if (size == 24) temp = asc2_2412[num][t]; 
        else return; 
        for (t1 = 0; t1 < 8; t1++) {
            if (temp & 0x80) LCD_DrawPoint(x, y);
            else if (mode == 0) { 
                // 覆盖背景色模式
                LCD_SetCursor(x, y);
                LCD_WriteRAM_Prepare();
                LCD_WR_DATA(BACK_COLOR);
            }
            temp <<= 1;
            y++;
            if (y >= LCD_H) return; 
            if ((y - y0) == size) {
                y = y0;
                x++;
                if (x >= LCD_W) return; 
                break;
            }
        }
    }
}

// 显示字符串
void LCD_ShowString(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint8_t size, char *p) {
    uint8_t x0 = x;
    width += x;
    height += y;
    while ((*p <= '~') && (*p >= ' ')) {
        if (x >= width) { x = x0; y += size; }
        if (y >= height) break;
        LCD_ShowChar(x, y, *p, size, 0);
        x += size / 2;
        p++;
    }
}

//----------------- 初始化 (解决白屏) -----------------
void LCD_Init(void) {
    // 1. 开启背光 (根据原理图，通常是 PB15)
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_15, GPIO_PIN_SET);
    delay_ms(50); 

    // 2. 软件复位 (关键步骤！解决白屏)
    // 即使硬件复位没接好，这步也能救活屏幕
    LCD_WR_REG(0x01); // Software Reset
    delay_ms(120);    // 必须等待

    LCD_WR_REG(0x11); // Sleep Out
    delay_ms(120);

    // 3. 读取ID (可选)
    // 尝试读取，读不到就强制按 9341 处理
    LCD_WR_REG(0xD3);
    LCD_ID = LCD_RD_DATA(); // dummy
    LCD_ID = LCD_RD_DATA(); // 0x00
    LCD_ID = LCD_RD_DATA(); // 0x93
    LCD_ID <<= 8;
    LCD_ID |= LCD_RD_DATA(); // 0x41
    
    if(LCD_ID != 0x9341 && LCD_ID != 0x5310 && LCD_ID != 0x7789) {
        LCD_ID = 0x9341; // 强制默认值
    }

    // 4. 初始化序列 (ILI9341)
    LCD_WR_REG(0xCF); LCD_WR_DATA(0x00); LCD_WR_DATA(0xC1); LCD_WR_DATA(0x30); 
    LCD_WR_REG(0xED); LCD_WR_DATA(0x64); LCD_WR_DATA(0x03); LCD_WR_DATA(0x12); LCD_WR_DATA(0x81); 
    LCD_WR_REG(0xE8); LCD_WR_DATA(0x85); LCD_WR_DATA(0x10); LCD_WR_DATA(0x78); 
    LCD_WR_REG(0xCB); LCD_WR_DATA(0x39); LCD_WR_DATA(0x2C); LCD_WR_DATA(0x00); LCD_WR_DATA(0x34); LCD_WR_DATA(0x02); 
    LCD_WR_REG(0xF7); LCD_WR_DATA(0x20); 
    LCD_WR_REG(0xEA); LCD_WR_DATA(0x00); LCD_WR_DATA(0x00); 
    LCD_WR_REG(0xC0); LCD_WR_DATA(0x1B); 
    LCD_WR_REG(0xC1); LCD_WR_DATA(0x01); 
    LCD_WR_REG(0xC5); LCD_WR_DATA(0x30); LCD_WR_DATA(0x30); 
    LCD_WR_REG(0xC7); LCD_WR_DATA(0xB7); 
    
    // 方向控制
    LCD_WR_REG(0x36); LCD_WR_DATA(0x48); // 竖屏, 如果显示反了改这里 (例如 0x08, 0x88)
    
    LCD_WR_REG(0x3A); LCD_WR_DATA(0x55); 
    LCD_WR_REG(0xB1); LCD_WR_DATA(0x00); LCD_WR_DATA(0x1A); 
    LCD_WR_REG(0xB6); LCD_WR_DATA(0x08); LCD_WR_DATA(0x82); LCD_WR_DATA(0x27); 
    LCD_WR_REG(0xF2); LCD_WR_DATA(0x00); 
    LCD_WR_REG(0x26); LCD_WR_DATA(0x01); 
    LCD_WR_REG(0xE0); LCD_WR_DATA(0x0F); LCD_WR_DATA(0x2A); LCD_WR_DATA(0x28); LCD_WR_DATA(0x08); LCD_WR_DATA(0x0E); LCD_WR_DATA(0x08); LCD_WR_DATA(0x54); LCD_WR_DATA(0xA9); LCD_WR_DATA(0x43); LCD_WR_DATA(0x0A); LCD_WR_DATA(0x0F); LCD_WR_DATA(0x00); LCD_WR_DATA(0x00); LCD_WR_DATA(0x00); LCD_WR_DATA(0x00); 		 
    LCD_WR_REG(0xE1); LCD_WR_DATA(0x00); LCD_WR_DATA(0x15); LCD_WR_DATA(0x17); LCD_WR_DATA(0x07); LCD_WR_DATA(0x11); LCD_WR_DATA(0x06); LCD_WR_DATA(0x2B); LCD_WR_DATA(0x56); LCD_WR_DATA(0x3C); LCD_WR_DATA(0x05); LCD_WR_DATA(0x10); LCD_WR_DATA(0x0F); LCD_WR_DATA(0x3F); LCD_WR_DATA(0x3F); LCD_WR_DATA(0x0F); 
    
    LCD_WR_REG(0x29); // Display ON
    LCD_Clear(WHITE); 
}