#ifndef __LCD_H
#define __LCD_H

#include "main.h"
#include "stdlib.h"

//----------------- 屏幕参数 ----------------
extern uint16_t LCD_W;
extern uint16_t LCD_H;
extern uint16_t POINT_COLOR;
extern uint16_t BACK_COLOR;

//----------------- 颜色定义 ----------------
#define WHITE         0xFFFF
#define BLACK         0x0000
#define BLUE          0x001F
#define BRED          0XF81F
#define GRED          0XFFE0
#define GBLUE         0X07FF
#define RED           0xF800
#define MAGENTA       0xF81F
#define GREEN         0x07E0
#define CYAN          0x7FFF
#define YELLOW        0xFFE0
#define BROWN         0XBC40
#define BRRED         0XFC07
#define GRAY          0X8430

//----------------- 核心地址定义 ----------------
// 针对 FSMC Bank4 (NE4) + 地址线 A6 (PF12)
// 基地址: 0x6C000000
// A6偏移: 1<<(6+1) = 128 = 0x80 (16位宽模式下地址左移1位)

// 写命令: A6=0 -> 0x6C000000
#define LCD_CMD_ADDR  (__IO uint16_t *)(0x6C000000)
// 写数据: A6=1 -> 0x6C000080
#define LCD_DATA_ADDR (__IO uint16_t *)(0x6C000080)

// 读写宏 (最快速度)
#define LCD_WR_REG(reg)   (*LCD_CMD_ADDR = reg)
#define LCD_WR_DATA(data) (*LCD_DATA_ADDR = data)
#define LCD_RD_DATA()     (*LCD_DATA_ADDR)

//----------------- 函数声明 ----------------
void LCD_Init(void);
void LCD_Clear(uint16_t Color);
void LCD_SetCursor(uint16_t Xpos, uint16_t Ypos);
void LCD_DrawPoint(uint16_t x, uint16_t y);
void LCD_DrawLine(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2);
void LCD_DrawRectangle(uint16_t x1, uint16_t y1, uint16_t x2, uint16_t y2);
void LCD_Fill(uint16_t sx, uint16_t sy, uint16_t ex, uint16_t ey, uint16_t color);
void LCD_ShowString(uint16_t x, uint16_t y, uint16_t width, uint16_t height, uint8_t size, char *p);

// 兼容旧代码的底层函数
void LCD_WriteReg(uint16_t LCD_Reg, uint16_t LCD_RegValue);
void LCD_WriteCmd(uint16_t Cmd);
void LCD_WriteData(uint16_t Data);

#endif