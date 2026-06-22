# MiSans 字体文件夹

## 如何添加 MiSans 字体文件

请将 MiSans 字体文件放入此文件夹，支持的格式：

### 推荐格式（按优先级）
1. **WOFF2** - 最佳压缩率，现代浏览器支持
2. **WOFF** - 较旧浏览器支持
3. **TTF** - 后备格式

### 文件命名要求
将字体文件重命名为以下名称：

```
MiSans-Regular.woff2      (常规体，400)
MiSans-Medium.woff2       (中等，500)
MiSans-SemiBold.woff2     (半粗，600)
MiSans-Bold.woff2         (粗体，700)
MiSans-ExtraBold.woff2    (特粗，800)
```

如果只有常规体，只需放置 `MiSans-Regular.woff2` 即可，其他字重会自动回退。

### 字体来源
MiSans 字体可以从以下渠道获取：
- 小米官方 GitHub 仓库
- 小米官网下载中心
- 或者使用系统自带的 MiSans 字体文件

### 字体文件夹结构
```
static/
└── fonts/
    ├── fonts.css          (字体加载样式)
    ├── MiSans-Regular.woff2
    ├── MiSans-Medium.woff2
    ├── MiSans-SemiBold.woff2
    ├── MiSans-Bold.woff2
    └── MiSans-ExtraBold.woff2
```

### 注意事项
- 字体文件大小：每个字重约 1-3MB
- WOFF2 格式可将文件压缩约 40%
- 网站会自动使用本地缓存的字体，提升加载速度
