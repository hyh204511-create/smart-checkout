#ifndef __VOICE_H
#define __VOICE_H

#include "main.h"
#include <stdarg.h>
#include <stdio.h>

// --- GBK/GB2312 十六进制编码 (解决乱码且防止编译器解析错误) ---
#define V_HUAN_YING  "\xBB\xB6\xD3\xAD\xCA\xB9\xD3\xC3" 
#define V_QING_LING  "\xC7\xE5\xC1\xE3"                 
#define V_SHI_BIE    "\xCA\xB6\xB1\xF0"                 
#define V_DAN_JIA    "\xB5\xA5\xBC\xDB"                 
#define V_DIAN       "\xB5\xE3"                         
#define V_YUAN       "\xD4\xAA"                         
#define V_GONG       "\xB9\xB2"                         

// 商品名称
#define V_PING_GUO   "\xC6\xBB\xB9\xFB"                 
#define V_XIANG_JIAO "\xCF\xE3\xBD\xB6"                 
#define V_CHENG_ZI   "\xB3\xC8\xD7\xD3"                 

// 函数原型
void Voice_Init(void);
void Voice_Speak(const char* fmt, ...);

#endif
/* 必须保留此空行，防止 AC5 编译器报错 */